#!/usr/bin/env python3
"""
Fix Deck Words Integrity

This script fixes two data integrity issues in quiz_deck_words:

1. Words that were incorrectly saved as "custom" (word_id=NULL) but match
   existing words in collection_words - restores the word_id link

2. Words with word_id set but missing UserWord record - creates the
   UserWord record so statistics work correctly

Usage:
    python scripts/fix_deck_words_integrity.py          # Dry run
    python scripts/fix_deck_words_integrity.py --apply  # Apply changes
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.db import db
from app.study.models import QuizDeckWord, QuizDeck, UserWord
from app.words.models import CollectionWords


def fix_custom_words_matching_collection(dry_run=True):
    """
    Fix #1: Find quiz_deck_words with word_id=NULL where custom_english
    matches an existing word in collection_words.

    Updates:
    - Sets word_id to the matching collection word
    - Clears custom_english/custom_russian (not needed when linked)
    - Creates UserWord if needed

    Returns count of fixed records.
    """
    print("\n" + "=" * 70)
    print("FIX #1: Restoring word_id for words matching collection")
    print("=" * 70)

    # Find all deck words with NULL word_id but custom_english set
    orphan_words = QuizDeckWord.query.filter(
        QuizDeckWord.word_id.is_(None),
        QuizDeckWord.custom_english.isnot(None)
    ).all()

    print(f"\nFound {len(orphan_words)} deck words with word_id=NULL and custom_english set")

    fixed_count = 0
    for dw in orphan_words:
        # Find matching word in collection_words
        matching_word = CollectionWords.query.filter(
            db.func.lower(CollectionWords.english_word) == db.func.lower(dw.custom_english.strip())
        ).first()

        if matching_word:
            # Get the deck to find the user
            deck = QuizDeck.query.get(dw.deck_id)
            if not deck:
                continue

            print(f"\n  Match found:")
            print(f"    QuizDeckWord ID: {dw.id}")
            print(f"    Deck: {deck.title} (user_id={deck.user_id})")
            print(f"    custom_english: '{dw.custom_english}'")
            print(f"    custom_russian: '{dw.custom_russian}'")
            print(f"    -> collection_words ID: {matching_word.id}")
            print(f"    -> english_word: '{matching_word.english_word}'")
            print(f"    -> russian_word: '{matching_word.russian_word}'")

            if not dry_run:
                # Update word_id
                dw.word_id = matching_word.id

                # Create UserWord if not exists
                user_word = UserWord.get_or_create(deck.user_id, matching_word.id)
                dw.user_word_id = user_word.id

                # Keep custom fields for now (they might have user's preferred translation)
                # dw.custom_english = None
                # dw.custom_russian = None

                print(f"    -> FIXED: word_id={matching_word.id}, user_word_id={user_word.id}")

            fixed_count += 1

    if not dry_run and fixed_count > 0:
        db.session.commit()

    print(f"\n{'Would fix' if dry_run else 'Fixed'}: {fixed_count} records")
    return fixed_count


def fix_missing_user_words(dry_run=True):
    """
    Fix #2: Find quiz_deck_words with word_id set but no corresponding
    UserWord record for the deck owner.

    Creates UserWord records so statistics work correctly.

    Returns count of created records.
    """
    print("\n" + "=" * 70)
    print("FIX #2: Creating missing UserWord records")
    print("=" * 70)

    # Find deck words with word_id but check if UserWord exists
    deck_words_with_word_id = QuizDeckWord.query.filter(
        QuizDeckWord.word_id.isnot(None)
    ).all()

    print(f"\nFound {len(deck_words_with_word_id)} deck words with word_id set")

    created_count = 0
    checked_pairs = set()  # (user_id, word_id) pairs we've already checked

    for dw in deck_words_with_word_id:
        # Get the deck to find the user
        deck = QuizDeck.query.get(dw.deck_id)
        if not deck:
            continue

        # Skip if we've already checked this pair
        pair_key = (deck.user_id, dw.word_id)
        if pair_key in checked_pairs:
            continue
        checked_pairs.add(pair_key)

        # Check if UserWord exists
        existing_user_word = UserWord.query.filter_by(
            user_id=deck.user_id,
            word_id=dw.word_id
        ).first()

        if not existing_user_word:
            word = CollectionWords.query.get(dw.word_id)
            word_text = word.english_word if word else f"ID={dw.word_id}"

            print(f"\n  Missing UserWord:")
            print(f"    user_id: {deck.user_id}")
            print(f"    word_id: {dw.word_id} ({word_text})")
            print(f"    deck: {deck.title}")

            if not dry_run:
                user_word = UserWord(user_id=deck.user_id, word_id=dw.word_id)
                db.session.add(user_word)
                db.session.flush()  # Get the ID

                # Update all deck words for this user/word pair
                QuizDeckWord.query.filter(
                    QuizDeckWord.word_id == dw.word_id,
                    QuizDeckWord.deck_id.in_(
                        db.session.query(QuizDeck.id).filter(QuizDeck.user_id == deck.user_id)
                    )
                ).update({QuizDeckWord.user_word_id: user_word.id}, synchronize_session=False)

                print(f"    -> CREATED: UserWord ID={user_word.id}")

            created_count += 1

    if not dry_run and created_count > 0:
        db.session.commit()

    print(f"\n{'Would create' if dry_run else 'Created'}: {created_count} UserWord records")
    return created_count


def update_user_word_ids(dry_run=True):
    """
    Fix #3: Update user_word_id in QuizDeckWord where it's NULL but
    UserWord exists for the deck owner.
    """
    print("\n" + "=" * 70)
    print("FIX #3: Updating missing user_word_id references")
    print("=" * 70)

    # Find deck words with word_id but no user_word_id
    deck_words_missing_ref = QuizDeckWord.query.filter(
        QuizDeckWord.word_id.isnot(None),
        QuizDeckWord.user_word_id.is_(None)
    ).all()

    print(f"\nFound {len(deck_words_missing_ref)} deck words with word_id but no user_word_id")

    updated_count = 0

    for dw in deck_words_missing_ref:
        deck = QuizDeck.query.get(dw.deck_id)
        if not deck:
            continue

        # Find UserWord
        user_word = UserWord.query.filter_by(
            user_id=deck.user_id,
            word_id=dw.word_id
        ).first()

        if user_word:
            print(f"\n  Updating QuizDeckWord ID={dw.id}:")
            print(f"    word_id: {dw.word_id}")
            print(f"    user_word_id: NULL -> {user_word.id}")

            if not dry_run:
                dw.user_word_id = user_word.id

            updated_count += 1

    if not dry_run and updated_count > 0:
        db.session.commit()

    print(f"\n{'Would update' if dry_run else 'Updated'}: {updated_count} records")
    return updated_count


def print_summary(results, dry_run):
    """Print final summary."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_changes = sum(results.values())

    print(f"\nFix #1 - Restored word_id links: {results['restored_word_ids']}")
    print(f"Fix #2 - Created UserWord records: {results['created_user_words']}")
    print(f"Fix #3 - Updated user_word_id refs: {results['updated_refs']}")
    print(f"\nTotal changes: {total_changes}")

    if dry_run:
        print("\n" + "-" * 70)
        print("DRY RUN - No changes were made")
        print("Run with --apply to apply these changes")
    else:
        print("\n" + "-" * 70)
        print("Changes have been committed to the database")


def main():
    """Main routine."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix data integrity issues in quiz_deck_words'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Actually modify the database (default: dry run)'
    )
    args = parser.parse_args()

    dry_run = not args.apply

    print("=" * 70)
    print("FIX DECK WORDS INTEGRITY")
    print("=" * 70)
    print(f"\nMode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will modify database)'}")

    if not dry_run:
        print("\n⚠️  WARNING: This will MODIFY the database!")
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            print("Aborted")
            return 0

    # Create Flask app context
    app = create_app()
    with app.app_context():
        results = {
            'restored_word_ids': fix_custom_words_matching_collection(dry_run),
            'created_user_words': fix_missing_user_words(dry_run),
            'updated_refs': update_user_word_ids(dry_run),
        }

        print_summary(results, dry_run)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
