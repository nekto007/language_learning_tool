"""
Deck Service - handles all deck-related business logic

Responsibilities:
- Deck CRUD operations
- Master deck synchronization (automatic decks)
- Deck word management
- Deck statistics
"""
from typing import List, Dict, Tuple, Optional
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.utils.db import db
from app.study.models import QuizDeck, QuizDeckWord, UserWord
from app.words.models import CollectionWords


class DeckService:
    """Service for managing quiz decks"""

    # Master deck titles
    LEARNING_DECK_TITLE = "Все мои слова"
    MASTERED_DECK_TITLE = "Выученные слова"

    @staticmethod
    def is_auto_deck(deck_title: str) -> bool:
        """Check if deck is automatically managed (master deck, reading, topic, or collection)"""
        # Check exact matches for master decks
        if deck_title in [DeckService.LEARNING_DECK_TITLE, DeckService.MASTERED_DECK_TITLE]:
            return True

        # Check exact match for reading words deck
        if deck_title == "Слова из чтения":
            return True

        # Check prefix matches for topic and collection decks
        if deck_title.startswith("Топик: ") or deck_title.startswith("Коллекция: "):
            return True

        return False

    @classmethod
    def sync_master_decks(cls, user_id: int) -> None:
        """
        Synchronize master decks with user's word collection

        Creates/updates two automatic decks:
        - "Все мои слова" (all learning words)
        - "Выученные слова" (mastered words)
        """
        # Get user's words by status
        learning_words = UserWord.query.filter(
            UserWord.user_id == user_id,
            UserWord.status != 'mastered'
        ).all()

        mastered_words = UserWord.query.filter(
            UserWord.user_id == user_id,
            UserWord.status == 'mastered'
        ).all()

        # Sync both decks
        cls._sync_deck(
            user_id,
            cls.LEARNING_DECK_TITLE,
            "Автоматическая колода со всеми вашими словами в процессе изучения",
            learning_words
        )

        cls._sync_deck(
            user_id,
            cls.MASTERED_DECK_TITLE,
            "Автоматическая колода с выученными словами",
            mastered_words
        )

        db.session.commit()

    @classmethod
    def _sync_deck(cls, user_id: int, title: str, description: str, word_list: List[UserWord]) -> None:
        """Sync a single deck with given word list"""
        # Find or create deck
        deck = QuizDeck.query.filter_by(user_id=user_id, title=title).first()
        if not deck:
            deck = QuizDeck(
                title=title,
                description=description,
                user_id=user_id,
                is_public=False
            )
            db.session.add(deck)
            db.session.flush()
        else:
            deck.description = description

        # Get current and target word sets
        existing_word_ids = {row[0] for row in db.session.query(QuizDeckWord.word_id).filter_by(deck_id=deck.id).all()}
        target_word_ids = {uw.word_id for uw in word_list}

        # Remove words no longer in UserWord
        to_remove = existing_word_ids - target_word_ids
        if to_remove:
            QuizDeckWord.query.filter(
                QuizDeckWord.deck_id == deck.id,
                QuizDeckWord.word_id.in_(to_remove)
            ).delete(synchronize_session=False)

        # Add new words with proper order indices
        to_add = target_word_ids - existing_word_ids
        if to_add:
            # Get max existing order index for this deck
            max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter_by(deck_id=deck.id).scalar() or -1

            # Add new words with incrementing order indices
            for i, word_id in enumerate(to_add, start=1):
                deck_word = QuizDeckWord(deck_id=deck.id, word_id=word_id, order_index=max_order + i)
                db.session.add(deck_word)

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
        """Get detailed statistics for a deck"""
        deck = cls.get_deck_with_words(deck_id)
        if not deck:
            return None

        deck_word_ids = [dw.word_id for dw in deck.words if dw.word_id]

        if not deck_word_ids:
            return {
                'total': 0,
                'new': 0,
                'learning': 0,
                'review': 0,
                'mastered': 0
            }

        # Bulk load existing UserWords
        existing_user_words = db.session.query(UserWord.word_id, UserWord.status).filter(
            UserWord.user_id == user_id,
            UserWord.word_id.in_(deck_word_ids)
        ).all()
        existing_word_ids = {uw.word_id for uw in existing_user_words}

        # Count by status
        status_counts = {}
        for _, status in existing_user_words:
            status_counts[status] = status_counts.get(status, 0) + 1

        new_count = len([wid for wid in deck_word_ids if wid not in existing_word_ids])

        return {
            'total': len(deck_word_ids),
            'new': new_count,
            'learning': status_counts.get('learning', 0),
            'review': status_counts.get('review', 0),
            'mastered': status_counts.get('mastered', 0)
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
            new_deck_word = QuizDeckWord(
                deck_id=new_deck.id,
                word_id=deck_word.word_id,
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

            deck_word = QuizDeckWord(
                deck_id=deck_id,
                word_id=word_id,
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
            # Adding custom word
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
