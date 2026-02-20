"""
Deck Service - handles all deck-related business logic

Responsibilities:
- Deck CRUD operations
- Deck word management
- Deck statistics
"""
from typing import List, Dict, Tuple, Optional
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.study.models import QuizDeck, QuizDeckWord, UserWord, UserCardDirection
from app.words.models import CollectionWords


class DeckService:
    """Service for managing quiz decks"""

    @staticmethod
    def is_auto_deck(deck_title: str) -> bool:
        """Check if deck is automatically managed (reading, topic, or collection)"""
        # Check exact match for reading words deck
        if deck_title == "Слова из чтения":
            return True

        # Check prefix matches for topic and collection decks
        if deck_title.startswith("Топик: ") or deck_title.startswith("Коллекция: "):
            return True

        return False

    @classmethod
    def get_user_decks(cls, user_id: int, include_public: bool = True) -> List[QuizDeck]:
        """Get all decks available to user (owned + public)"""
        query = QuizDeck.query

        if include_public:
            query = query.filter(
                (QuizDeck.user_id == user_id) | (QuizDeck.is_public == True)
            )
        else:
            query = query.filter(QuizDeck.user_id == user_id)

        return query.order_by(QuizDeck.created_at.desc()).all()

    @classmethod
    def get_deck_with_words(cls, deck_id: int) -> Optional[QuizDeck]:
        """Get deck with words (words use lazy='dynamic' so no eager loading needed)"""
        return QuizDeck.query.get(deck_id)

    @classmethod
    def get_deck_statistics(cls, deck_id: int, user_id: int) -> Dict:
        """
        Get detailed statistics for a deck.

        Uses direct user_word relationship when available for efficiency.
        Falls back to word_id lookup for legacy records without user_word_id.
        """
        from sqlalchemy.orm import joinedload

        deck = cls.get_deck_with_words(deck_id)
        if not deck:
            return None

        # Load deck words with user_word relationship eagerly
        deck_words = deck.words.options(
            joinedload(QuizDeckWord.user_word)
        ).all()

        if not deck_words:
            return {
                'total': 0,
                'new': 0,
                'learning': 0,
                'review': 0,
                'mastered': 0
            }

        # Collect word_ids that need fallback lookup (no user_word_id set)
        fallback_word_ids = []
        for dw in deck_words:
            if dw.word_id and not dw.user_word_id:
                fallback_word_ids.append(dw.word_id)

        # Fallback: load UserWords for deck_words without user_word_id
        fallback_user_words = {}
        if fallback_word_ids:
            user_words = UserWord.query.filter(
                UserWord.user_id == user_id,
                UserWord.word_id.in_(fallback_word_ids)
            ).all()
            fallback_user_words = {uw.word_id: uw for uw in user_words}

        # Get min intervals for mastered calculation
        # Collect all user_word_ids we need to check
        user_word_ids_to_check = []
        for dw in deck_words:
            if dw.user_word and dw.user_word.status == 'review':
                user_word_ids_to_check.append(dw.user_word.id)
        for word_id, uw in fallback_user_words.items():
            if uw.status == 'review':
                user_word_ids_to_check.append(uw.id)

        min_intervals = {}
        if user_word_ids_to_check:
            interval_data = db.session.query(
                UserCardDirection.user_word_id,
                func.min(UserCardDirection.interval).label('min_interval')
            ).filter(
                UserCardDirection.user_word_id.in_(user_word_ids_to_check)
            ).group_by(UserCardDirection.user_word_id).all()
            min_intervals = {uw_id: min_int for uw_id, min_int in interval_data}

        # Count by status
        new_count = 0
        learning_count = 0
        review_count = 0
        mastered_count = 0
        total_with_word_id = 0

        for dw in deck_words:
            if not dw.word_id:
                # Custom word without word_id - count as new
                new_count += 1
                continue

            total_with_word_id += 1

            # Get user_word: prefer direct relationship, fallback to lookup
            user_word = dw.user_word
            if not user_word and dw.word_id in fallback_user_words:
                user_word = fallback_user_words[dw.word_id]

            if not user_word:
                new_count += 1
            else:
                status = user_word.status
                if status == 'new':
                    new_count += 1
                elif status == 'learning':
                    learning_count += 1
                elif status == 'review':
                    min_int = min_intervals.get(user_word.id, 0)
                    if min_int >= UserWord.MASTERED_THRESHOLD_DAYS:
                        mastered_count += 1
                    else:
                        review_count += 1
                elif status == 'mastered':
                    mastered_count += 1

        return {
            'total': len(deck_words),
            'new': new_count,
            'learning': learning_count,
            'review': review_count,
            'mastered': mastered_count
        }

    @classmethod
    def create_deck(cls, user_id: int, title: str, description: str = "", is_public: bool = False) -> QuizDeck:
        """Create a new deck"""
        deck = QuizDeck(
            user_id=user_id,
            title=title,
            description=description,
            is_public=is_public
        )

        # Generate share code if public
        if is_public:
            deck.generate_share_code()

        db.session.add(deck)
        db.session.flush()

        from app.auth.models import User
        user = User.query.get(user_id)
        if not user.default_study_deck_id:
            user.default_study_deck_id = deck.id

        db.session.commit()
        return deck

    @classmethod
    def update_deck(cls, deck_id: int, user_id: int, title: str = None, description: str = None,
                   is_public: bool = None, generate_share: bool = False,
                   new_words_per_day: int = None, reviews_per_day: int = None) -> Tuple[Optional[QuizDeck], Optional[str]]:
        """Update deck details including per-deck limits"""
        from datetime import datetime, timezone

        deck = QuizDeck.query.get(deck_id)

        if not deck:
            return None, "Колода не найдена"

        if deck.user_id != user_id:
            return None, "Нет доступа к этой колоде"

        if cls.is_auto_deck(deck.title):
            return None, "Нельзя редактировать автоматическую колоду"

        was_public = deck.is_public

        if title:
            deck.title = title
        if description is not None:
            deck.description = description
        if is_public is not None:
            deck.is_public = is_public

        # Update per-deck limits (None means use global settings)
        # We accept 'unchanged' sentinel to distinguish from None (use global)
        if new_words_per_day is not None:
            if new_words_per_day == 0:
                deck.new_words_per_day = None  # 0 means use global
            else:
                deck.new_words_per_day = new_words_per_day
        if reviews_per_day is not None:
            if reviews_per_day == 0:
                deck.reviews_per_day = None  # 0 means use global
            else:
                deck.reviews_per_day = reviews_per_day

        # Generate share code if making public
        if generate_share and deck.is_public and not was_public and not deck.share_code:
            deck.generate_share_code()

        deck.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        # Sync to forks if public original deck
        if deck.is_public and deck.parent_deck_id is None:
            deck.sync_to_forks()

        return deck, None

    @classmethod
    def delete_deck(cls, deck_id: int, user_id: int) -> Tuple[bool, Optional[str]]:
        """Delete a deck"""
        deck = QuizDeck.query.get(deck_id)

        if not deck:
            return False, "Колода не найдена"

        if deck.user_id != user_id:
            return False, "Нет доступа к этой колоде"

        if cls.is_auto_deck(deck.title):
            return False, "Нельзя удалить автоматическую колоду"

        db.session.delete(deck)
        db.session.commit()
        return True, None

    @classmethod
    def copy_deck(cls, deck_id: int, user_id: int) -> Tuple[Optional[QuizDeck], Optional[str]]:
        """Copy a deck to user's collection"""
        from datetime import datetime, timezone

        original_deck = cls.get_deck_with_words(deck_id)

        if not original_deck:
            return None, "Колода не найдена"

        # Check access
        if not original_deck.is_public and original_deck.user_id != user_id:
            return None, "У вас нет доступа к этой колоде"

        # Check if already copied
        existing_copy = QuizDeck.query.filter_by(
            user_id=user_id,
            title=f"{original_deck.title} (копия)"
        ).first()

        if existing_copy:
            return existing_copy, "Вы уже скопировали эту колоду"

        # Create new deck
        new_deck = QuizDeck(
            user_id=user_id,
            title=f"{original_deck.title} (копия)",
            description=original_deck.description,
            is_public=False,
            parent_deck_id=original_deck.id,  # Link to parent for sync
            last_synced_at=datetime.now(timezone.utc)
        )
        db.session.add(new_deck)
        db.session.flush()

        # Copy words with all fields
        for deck_word in original_deck.words:
            # Get or create UserWord for the new owner (if word_id exists)
            user_word_id = None
            if deck_word.word_id:
                user_word = UserWord.get_or_create(user_id, deck_word.word_id)
                user_word_id = user_word.id

            new_deck_word = QuizDeckWord(
                deck_id=new_deck.id,
                word_id=deck_word.word_id,
                user_word_id=user_word_id,  # Link to new owner's UserWord
                custom_english=deck_word.custom_english,
                custom_russian=deck_word.custom_russian,
                order_index=deck_word.order_index
            )
            db.session.add(new_deck_word)

        db.session.commit()
        return new_deck, None

    @classmethod
    def add_word_to_deck(cls, deck_id: int, user_id: int, word_id: int = None,
                        custom_english: str = None, custom_russian: str = None,
                        custom_sentences: str = None) -> Tuple[Optional[QuizDeckWord], Optional[str]]:
        """Add a word to deck (from collection or custom)"""
        deck = QuizDeck.query.get(deck_id)

        if not deck:
            return None, "Колода не найдена"

        if deck.user_id != user_id:
            return None, "Нет доступа к этой колоде"

        if cls.is_auto_deck(deck.title):
            return None, "Нельзя добавлять слова в автоматическую колоду"

        # Validate input
        if not custom_english or not custom_russian:
            return None, "Необходимо заполнить оба поля"

        # Get max order index
        max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
            QuizDeckWord.deck_id == deck_id
        ).scalar() or 0

        if word_id:
            # Adding from collection
            word = CollectionWords.query.get(word_id)
            if not word:
                return None, "Слово не найдено"

            # Check if already in deck
            existing = QuizDeckWord.query.filter_by(
                deck_id=deck_id,
                word_id=word_id
            ).first()

            if existing:
                return None, "Это слово уже в колоде"

            # Get or create UserWord to link to deck_word
            user_word = UserWord.get_or_create(user_id, word_id)

            deck_word = QuizDeckWord(
                deck_id=deck_id,
                word_id=word_id,
                user_word_id=user_word.id,  # Link to user's word learning status
                order_index=max_order + 1
            )

            # Save custom override if different
            if custom_english != word.english_word or custom_russian != word.russian_word:
                deck_word.custom_english = custom_english
                deck_word.custom_russian = custom_russian

            # Save custom sentences if provided and different
            if custom_sentences and (not word.sentences or custom_sentences != word.sentences):
                deck_word.custom_sentences = custom_sentences
        else:
            # Adding custom word (no word_id, no user_word_id)
            deck_word = QuizDeckWord(
                deck_id=deck_id,
                custom_english=custom_english,
                custom_russian=custom_russian,
                custom_sentences=custom_sentences if custom_sentences else None,
                order_index=max_order + 1
            )

        db.session.add(deck_word)
        db.session.commit()
        return deck_word, None

    @classmethod
    def edit_deck_word(cls, deck_id: int, deck_word_id: int, user_id: int,
                       custom_english: str, custom_russian: str,
                       custom_sentences: str = None) -> Tuple[Optional[QuizDeckWord], Optional[str]]:
        """Edit word in deck (update custom fields)"""
        deck = QuizDeck.query.get(deck_id)

        if not deck:
            return None, "Колода не найдена"

        if deck.user_id != user_id:
            return None, "Нет доступа к этой колоде"

        if cls.is_auto_deck(deck.title):
            return None, "Нельзя редактировать слова в автоматической колоде"

        deck_word = QuizDeckWord.query.filter_by(deck_id=deck_id, id=deck_word_id).first()
        if not deck_word:
            return None, "Слово не найдено в колоде"

        if not custom_english or not custom_russian:
            return None, "Необходимо заполнить оба поля"

        # Update custom fields
        deck_word.custom_english = custom_english
        deck_word.custom_russian = custom_russian
        deck_word.custom_sentences = custom_sentences if custom_sentences else None

        db.session.commit()
        return deck_word, None

    @classmethod
    def remove_word_from_deck(cls, deck_id: int, deck_word_id: int, user_id: int) -> Tuple[bool, Optional[str]]:
        """Remove a word from deck (by deck_word id)"""
        deck = QuizDeck.query.get(deck_id)

        if not deck:
            return False, "Колода не найдена"

        if deck.user_id != user_id:
            return False, "Нет доступа к этой колоде"

        if cls.is_auto_deck(deck.title):
            return False, "Нельзя удалять слова из автоматической колоды"

        deck_word = QuizDeckWord.query.filter_by(deck_id=deck_id, id=deck_word_id).first()
        if not deck_word:
            return False, "Слово не найдено в колоде"

        db.session.delete(deck_word)
        db.session.commit()
        return True, None

    @classmethod
    def add_bulk_words_to_deck(cls, deck_id: int, user_id: int, word_ids: List[int]) -> Tuple[int, int]:
        """
        Add multiple words to a deck in bulk.

        Args:
            deck_id: Target deck ID
            user_id: Owner user ID
            word_ids: List of CollectionWords IDs to add

        Returns:
            Tuple of (added_count, skipped_count)
        """
        deck = QuizDeck.query.get(deck_id)
        if not deck or deck.user_id != user_id:
            return 0, 0

        if cls.is_auto_deck(deck.title):
            return 0, 0

        if not word_ids:
            return 0, 0

        # Check which words already exist in deck
        existing = {row[0] for row in db.session.query(QuizDeckWord.word_id).filter(
            QuizDeckWord.deck_id == deck_id,
            QuizDeckWord.word_id.in_(word_ids)
        ).all()}

        # Get max order index
        max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
            QuizDeckWord.deck_id == deck_id
        ).scalar() or 0

        # Filter to new words only
        new_word_ids = [wid for wid in word_ids if wid not in existing]
        skipped = len(word_ids) - len(new_word_ids)

        if not new_word_ids:
            return 0, skipped

        # Ensure UserWord records exist for all new words
        existing_user_words = {row[0]: row[1] for row in db.session.query(
            UserWord.word_id, UserWord.id
        ).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(new_word_ids)
        ).all()}

        for i, word_id in enumerate(new_word_ids):
            # Create UserWord if needed
            if word_id not in existing_user_words:
                uw = UserWord(user_id=user_id, word_id=word_id)
                db.session.add(uw)
                db.session.flush()
                existing_user_words[word_id] = uw.id

            # Create QuizDeckWord
            deck_word = QuizDeckWord(
                deck_id=deck_id,
                word_id=word_id,
                user_word_id=existing_user_words[word_id],
                order_index=max_order + i + 1
            )
            db.session.add(deck_word)

        db.session.commit()
        return len(new_word_ids), skipped

    @classmethod
    def search_words(cls, query: str, limit: int = 20) -> List[CollectionWords]:
        """Search words in collection with smart sorting"""
        from sqlalchemy import case

        if not query or len(query) < 2:
            return []

        # Search in both english and russian
        words_query = CollectionWords.query.filter(
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != '',
            db.or_(
                CollectionWords.english_word.ilike(f'%{query}%'),
                CollectionWords.russian_word.ilike(f'%{query}%')
            )
        )

        # Smart sorting: exact match > starts with > contains
        query_lower = query.lower()
        words_query = words_query.order_by(
            case(
                (func.lower(CollectionWords.english_word) == query_lower, 1),
                (func.lower(CollectionWords.russian_word) == query_lower, 1),
                else_=10
            ),
            case(
                (func.lower(CollectionWords.english_word).like(f'{query_lower}%'), 2),
                (func.lower(CollectionWords.russian_word).like(f'{query_lower}%'), 2),
                else_=10
            ),
            CollectionWords.english_word
        )

        return words_query.limit(limit).all()
