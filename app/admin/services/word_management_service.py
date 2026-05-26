# app/admin/services/word_management_service.py

"""
Сервис для управления словами (Word Management Service)
Обрабатывает импорт, экспорт, массовые обновления и статистику слов
"""
import csv
import logging
import re
from difflib import SequenceMatcher
from io import StringIO

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.books.models import Book
from app.study.models import UserWord
from app.utils.audio import get_clean_audio_filename
from app.utils.db import db
from app.words.models import CollectionWords, Topic

logger = logging.getLogger(__name__)


FREQUENCY_BAND_MAP = {
    'high': 1,
    'medium': 2,
    'low': 3,
    '1': 1,
    '2': 2,
    '3': 3,
}

IMPORT_BASE_COLUMNS = 5
IMPORT_ENRICHED_COLUMNS = 11
IMPORT_BILINGUAL_TOPIC_COLUMNS = 12
IMPORT_HEADER_NAMES = {'english_word', 'word', 'english'}
TOPIC_SUGGESTION_THRESHOLD = 0.72
TOPIC_TOKEN_ALIASES = {
    'action': 'action',
    'actions': 'action',
    'verb': 'action',
    'verbs': 'action',
    'действие': 'action',
    'действия': 'action',
    'food': 'food',
    'drink': 'drink',
    'drinks': 'drink',
    'еда': 'food',
    'напиток': 'drink',
    'напитки': 'drink',
    'animal': 'animal',
    'animals': 'animal',
    'pet': 'animal',
    'pets': 'animal',
    'животное': 'animal',
    'животные': 'animal',
    'питомец': 'animal',
    'питомцы': 'animal',
    'body': 'body',
    'тело': 'body',
    'health': 'health',
    'здоровье': 'health',
    'здоровья': 'health',
    'career': 'work',
    'careers': 'work',
    'employment': 'work',
    'job': 'work',
    'jobs': 'work',
    'profession': 'work',
    'professions': 'work',
    'work': 'work',
    'работа': 'work',
    'работы': 'work',
    'карьера': 'work',
    'карьеры': 'work',
    'emotion': 'emotion',
    'emotions': 'emotion',
    'emotional': 'emotion',
    'feeling': 'emotion',
    'feelings': 'emotion',
    'mood': 'emotion',
    'state': 'state',
    'эмоция': 'emotion',
    'эмоции': 'emotion',
    'чувство': 'emotion',
    'чувства': 'emotion',
    'настроение': 'emotion',
    'personality': 'personality',
    'character': 'personality',
    'личность': 'personality',
    'характер': 'personality',
    'transport': 'transport',
    'transportation': 'transport',
    'транспорт': 'transport',
    'travel': 'travel',
    'travels': 'travel',
    'tourism': 'travel',
    'trip': 'travel',
    'trips': 'travel',
    'путешествие': 'travel',
    'путешествия': 'travel',
    'поездка': 'travel',
    'поездки': 'travel',
}
TOPIC_STOP_WORDS = {'and', 'or', 'of', 'the', 'и', 'или', 'care', 'уход'}
TOPIC_ANCHOR_TOKEN_SCORES = {
    'action': 0.86,
    'animal': 0.86,
    'body': 0.86,
    'drink': 0.86,
    'food': 0.86,
    'health': 0.86,
    'emotion': 0.86,
    'personality': 0.86,
    'transport': 0.86,
    'travel': 0.86,
    'work': 0.86,
}


class WordManagementService:
    """Сервис для управления словами и их статистикой"""

    @staticmethod
    def _parse_list_field(value):
        """Parse comma-separated import cell into a JSON-list value."""
        if not value:
            return None
        value = value.strip()
        if len(value) >= 2 and value.startswith('[') and value.endswith(']'):
            value = value[1:-1]
        items = [
            item.strip().strip('"\'')
            for item in value.split(',')
            if item.strip().strip('"\'')
        ]
        return items or None

    @staticmethod
    def _normalize_ipa(value):
        """Store IPA without wrapping slashes; templates add them on render."""
        if not value:
            return None
        value = value.strip()
        if len(value) >= 2 and value.startswith('/') and value.endswith('/'):
            value = value[1:-1].strip()
        return value or None

    @staticmethod
    def _parse_frequency_band(value):
        """Return DB frequency band value: 1=high, 2=medium, 3=low."""
        if not value:
            return None
        normalized = value.strip().lower()
        return FREQUENCY_BAND_MAP.get(normalized)

    @staticmethod
    def _build_topic_name(topic_ru, topic_en):
        """Build canonical user-facing topic name from import columns."""
        topic_ru = ' '.join((topic_ru or '').strip().split())
        topic_en = ' '.join((topic_en or '').strip().split())
        if topic_ru and topic_en:
            return f"{topic_ru} ({topic_en})"
        return topic_ru or topic_en or None

    @staticmethod
    def _normalize_topic_key(value):
        """Normalize topic names for exact and fuzzy matching."""
        value = (value or '').strip().lower().replace('ё', 'е')
        value = re.sub(r'\s+', ' ', value)
        value = re.sub(r'[^\w\sа-яa-z0-9]+', ' ', value, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', value).strip()

    @staticmethod
    def _topic_tokens(value):
        """Return canonical tokens for topic alias matching."""
        tokens = set()
        for token in WordManagementService._normalize_topic_key(value).split():
            if token in TOPIC_STOP_WORDS:
                continue
            tokens.add(TOPIC_TOKEN_ALIASES.get(token, token))
        return tokens

    @staticmethod
    def _topic_similarity_score(topic_name, existing_topic_name):
        """Score topic similarity using string ratio plus taxonomy token overlap."""
        topic_key = WordManagementService._normalize_topic_key(topic_name)
        existing_key = WordManagementService._normalize_topic_key(existing_topic_name)
        if not topic_key or not existing_key:
            return 0.0

        sequence_score = SequenceMatcher(None, topic_key, existing_key).ratio()
        topic_tokens = WordManagementService._topic_tokens(topic_name)
        existing_tokens = WordManagementService._topic_tokens(existing_topic_name)
        if not topic_tokens or not existing_tokens:
            return sequence_score

        shared_tokens = topic_tokens & existing_tokens
        if not shared_tokens:
            return sequence_score

        import_coverage = len(shared_tokens) / len(topic_tokens)
        dice_score = (2 * len(shared_tokens)) / (len(topic_tokens) + len(existing_tokens))
        anchor_score = max(
            TOPIC_ANCHOR_TOKEN_SCORES.get(token, 0.0)
            for token in shared_tokens
        )
        token_score = max(import_coverage, dice_score, anchor_score)

        # Short imported topics often name one part of a broader DB taxonomy
        # category, e.g. "транспорт (transport)" -> "... Transportation & Travel".
        if import_coverage == 1:
            token_score = max(token_score, 0.91)

        return max(sequence_score, token_score)

    @staticmethod
    def _get_topic_by_name(topic_name):
        """Return topic by normalized name, or None."""
        target_key = WordManagementService._normalize_topic_key(topic_name)
        if not target_key:
            return None
        for topic in Topic.query.all():
            if WordManagementService._normalize_topic_key(topic.name) == target_key:
                return topic
        return None

    @staticmethod
    def _get_or_create_topic(topic_name):
        """Return existing topic by normalized name or create a new one."""
        topic = WordManagementService._get_topic_by_name(topic_name)
        if topic is not None:
            return topic
        topic = Topic(name=topic_name)
        db.session.add(topic)
        db.session.flush()
        return topic

    @staticmethod
    def _find_topic_suggestion(topic_name, existing_topics):
        """Find the closest existing topic for preview suggestions."""
        topic_key = WordManagementService._normalize_topic_key(topic_name)
        if not topic_key:
            return None

        best_topic = None
        best_score = 0.0
        for topic in existing_topics:
            score = WordManagementService._topic_similarity_score(
                topic_name,
                topic.name,
            )
            if score > best_score:
                best_topic = topic
                best_score = score

        if best_topic is not None and best_score >= TOPIC_SUGGESTION_THRESHOLD:
            return {
                'id': best_topic.id,
                'name': best_topic.name,
                'score': round(best_score, 2),
            }
        return None

    @staticmethod
    def prepare_topic_resolution_preview(existing_words, missing_words):
        """Annotate import rows with topic resolution data for preview UI."""
        all_words = [*existing_words, *missing_words]
        existing_topics = Topic.query.order_by(Topic.name).all()
        existing_by_key = {
            WordManagementService._normalize_topic_key(topic.name): topic
            for topic in existing_topics
        }

        candidates_by_topic = {}
        for word_data in all_words:
            topic_name = word_data.get('topic')
            if not topic_name:
                continue

            topic_key = WordManagementService._normalize_topic_key(topic_name)
            matched_topic = existing_by_key.get(topic_key)
            if matched_topic is not None:
                word_data['topic_status'] = 'existing'
                word_data['topic_existing_id'] = matched_topic.id
                word_data['topic_existing_name'] = matched_topic.name
                continue

            candidate_key = f"topic_{len(candidates_by_topic) + 1}"
            existing_candidate = candidates_by_topic.get(topic_key)
            if existing_candidate is None:
                suggestion = WordManagementService._find_topic_suggestion(
                    topic_name,
                    existing_topics,
                )
                existing_candidate = {
                    'key': candidate_key,
                    'topic': topic_name,
                    'suggestion': suggestion,
                    'default_action': 'map' if suggestion else 'create',
                }
                candidates_by_topic[topic_key] = existing_candidate

            word_data['topic_status'] = 'needs_resolution'
            word_data['topic_resolution_key'] = existing_candidate['key']

        return {
            'topic_candidates': list(candidates_by_topic.values()),
            'topic_candidate_keys': [
                candidate['key'] for candidate in candidates_by_topic.values()
            ],
            'existing_topics': [
                {'id': topic.id, 'name': topic.name}
                for topic in existing_topics
            ],
        }

    @staticmethod
    def _build_topic_index():
        """Snapshot all topics keyed by normalized name + id for batch lookup.

        Used by the import flow to avoid issuing ``Topic.query.all()`` once
        per word (~1000+ rows on large imports).
        """
        topics = Topic.query.all()
        by_key: dict[str, Topic] = {}
        for t in topics:
            key = WordManagementService._normalize_topic_key(t.name)
            if key and key not in by_key:
                by_key[key] = t
        return {
            'by_key': by_key,
            'by_id': {t.id: t for t in topics},
        }

    @staticmethod
    def _resolve_import_topic(word_data, topic_resolutions=None, topic_index=None):
        """Resolve topic for one word based on preview choices.

        ``topic_index`` (from ``_build_topic_index``) avoids per-call DB hits;
        when None, falls back to direct queries (preserves legacy callers).
        """
        topic_name = word_data.get('topic')
        if not topic_name:
            return None

        def _lookup_by_name(name):
            if topic_index is None:
                return WordManagementService._get_topic_by_name(name)
            key = WordManagementService._normalize_topic_key(name)
            return topic_index['by_key'].get(key) if key else None

        def _lookup_by_id(tid):
            if topic_index is None:
                return Topic.query.get(int(tid))
            return topic_index['by_id'].get(int(tid))

        def _create(name):
            new_topic = Topic(name=name)
            db.session.add(new_topic)
            db.session.flush()
            if topic_index is not None:
                key = WordManagementService._normalize_topic_key(name)
                if key:
                    topic_index['by_key'][key] = new_topic
                topic_index['by_id'][new_topic.id] = new_topic
            return new_topic

        if topic_resolutions is None:
            existing = _lookup_by_name(topic_name)
            return existing if existing is not None else _create(topic_name)

        if word_data.get('topic_status') == 'existing':
            return _lookup_by_name(topic_name)

        resolution_key = word_data.get('topic_resolution_key')
        resolution = (topic_resolutions or {}).get(resolution_key, {})
        action = resolution.get('action', 'skip')

        if action == 'skip':
            return None
        if action == 'map':
            topic_id = resolution.get('topic_id')
            if not topic_id:
                return None
            return _lookup_by_id(topic_id)
        if action == 'create':
            existing = _lookup_by_name(topic_name)
            return existing if existing is not None else _create(topic_name)
        return None

    @staticmethod
    def _apply_enrichment_fields(word, word_data, topic_resolutions=None, topic_index=None):
        """Apply optional enrichment fields without overwriting with blanks."""
        if word_data.get('ipa_transcription'):
            word.ipa_transcription = word_data['ipa_transcription']
        if word_data.get('synonyms') is not None:
            word.synonyms = word_data['synonyms']
        if word_data.get('antonyms') is not None:
            word.antonyms = word_data['antonyms']
        if word_data.get('frequency_band') is not None:
            word.frequency_band = word_data['frequency_band']
        if word_data.get('etymology'):
            word.etymology = word_data['etymology']

        topic_name = (word_data.get('topic') or '').strip()
        if topic_name and hasattr(word, 'topics'):
            topic = WordManagementService._resolve_import_topic(
                word_data,
                topic_resolutions=topic_resolutions,
                topic_index=topic_index,
            )
            if topic is not None and topic not in word.topics:
                word.topics.append(topic)

    @staticmethod
    def get_word_statistics():
        """
        Получает общую статистику по словам

        Returns:
            dict: Статистика с ключами: words_total, status_stats,
                  recent_words, words_without_translation
        """
        try:
            # Общая статистика по словам
            words_total = CollectionWords.query.count()

            # Статистика по статусам пользователей
            status_stats = db.session.query(
                UserWord.status,
                func.count(UserWord.id).label('count')
            ).group_by(UserWord.status).all()

            # Недавно добавленные слова
            recent_words = CollectionWords.query.order_by(
                CollectionWords.id.desc()
            ).limit(10).all()

            # Слова без переводов
            words_without_translation = CollectionWords.query.filter(
                (CollectionWords.russian_word == None) |
                (CollectionWords.russian_word == '')
            ).count()

            return {
                'words_total': words_total,
                'status_stats': status_stats,
                'recent_words': recent_words,
                'words_without_translation': words_without_translation
            }
        except Exception as e:
            logger.error(f"Error getting word statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def get_detailed_statistics():
        """
        Получает детальную статистику по словам для страницы статистики

        Returns:
            dict: Детальная статистика с разбивкой по статусам,
                  уровням, пользователям и книгам
        """
        try:
            # Статистика по статусам
            status_stats = db.session.query(
                UserWord.status,
                func.count(UserWord.id).label('count'),
                func.count(func.distinct(UserWord.user_id)).label('users')
            ).group_by(UserWord.status).all()

            # Статистика по уровням
            level_stats = db.session.query(
                CollectionWords.level,
                func.count(CollectionWords.id).label('count')
            ).group_by(CollectionWords.level).all()

            # Топ пользователей по количеству изучаемых слов
            top_users = db.session.query(
                User.username,
                func.count(UserWord.id).label('word_count')
            ).join(
                UserWord, User.id == UserWord.user_id
            ).group_by(
                User.id, User.username
            ).order_by(
                func.count(UserWord.id).desc()
            ).limit(10).all()

            # Статистика по книгам
            book_stats = db.session.query(
                Book.title,
                Book.words_total,
                Book.unique_words
            ).order_by(Book.words_total.desc()).limit(10).all()

            return {
                'status_stats': status_stats,
                'level_stats': level_stats,
                'top_users': top_users,
                'book_stats': book_stats
            }
        except Exception as e:
            logger.error(f"Error getting detailed word statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def bulk_update_word_status(words, status, user_id=None):
        """
        Массово обновляет статус слов для пользователей.

        Flush only — caller commits inside the same transaction as the
        audit-log entry so both become durable together (or roll back together).

        Args:
            words: Список английских слов (строки)
            status: Новый статус для слов
            user_id: ID конкретного пользователя (если None - для всех активных)

        Returns:
            tuple: (success: bool, updated_count: int, total_requested: int, error: str)
        """
        try:
            if not words or not status:
                return False, 0, 0, 'Требуются words и status'

            if not isinstance(words, list):
                return False, 0, 0, 'Требуются words и status'

            # Normalize once; preserve order and skip blanks.
            normalized = []
            seen = set()
            for raw in words:
                if not isinstance(raw, str):
                    continue
                key = raw.lower().strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                normalized.append(key)

            if not normalized:
                return False, 0, 0, 'Требуются words и status'

            if user_id is None:
                user_ids = [
                    uid for (uid,) in db.session.query(User.id)
                    .filter(User.active.is_(True))
                    .all()
                ]
            else:
                user_ids = [user_id]

            if not user_ids:
                logger.info("Bulk status update: no target users")
                return True, 0, 0, None

            existing_words = CollectionWords.query.filter(
                CollectionWords.english_word.in_(normalized)
            ).all()

            updated_count = 0
            for word in existing_words:
                for uid in user_ids:
                    user = db.session.get(User, uid)
                    if user is None:
                        continue
                    user.set_word_status(word.id, status)
                    updated_count += 1

            db.session.flush()
            total_requested = len(normalized) * len(user_ids)

            logger.info(
                "Bulk status update prepared: %d updates to status=%s for %d words across %d users",
                updated_count, status, len(normalized), len(user_ids),
            )
            return True, updated_count, total_requested, None

        except Exception as e:
            logger.error(f"Error in bulk status update: {str(e)}")
            db.session.rollback()
            return False, 0, 0, str(e)

    @staticmethod
    def get_words_for_export(status=None, user_id=None):
        """
        Получает слова для экспорта по критериям

        Args:
            status: Фильтр по статусу слов
            user_id: Фильтр по ID пользователя

        Returns:
            list: Список слов с атрибутами для экспорта
        """
        try:
            if status and user_id:
                # Экспорт слов конкретного пользователя по статусу
                words_query = db.session.query(
                    CollectionWords.english_word,
                    CollectionWords.russian_word,
                    CollectionWords.level,
                    UserWord.status
                ).join(
                    UserWord, CollectionWords.id == UserWord.word_id
                ).filter(
                    UserWord.user_id == user_id,
                    UserWord.status == status
                )
            elif status:
                # Экспорт всех слов по статусу (любых пользователей)
                words_query = db.session.query(
                    CollectionWords.english_word,
                    CollectionWords.russian_word,
                    CollectionWords.level,
                    UserWord.status
                ).join(
                    UserWord, CollectionWords.id == UserWord.word_id
                ).filter(UserWord.status == status).distinct()
            else:
                # Экспорт всех слов
                words_query = db.session.query(
                    CollectionWords.english_word,
                    CollectionWords.russian_word,
                    CollectionWords.level
                )

            return words_query.all()

        except Exception as e:
            logger.error(f"Error getting words for export: {str(e)}")
            return []

    @staticmethod
    def parse_import_file(content):
        """
        Парсит содержимое файла импорта переводов

        Args:
            content: Текстовое содержимое файла

        Returns:
            tuple: (existing_words: list, missing_words: list, errors: list)

        Batched lookup: walks all rows once to build word_data dicts,
        then issues a single ``IN(...)`` query against CollectionWords to
        decide existing vs missing — avoiding ~one query per line on
        large imports (1000+ lines previously took >30s).
        """
        existing_words = []
        missing_words = []
        errors = []
        parsed_rows: list[dict] = []

        reader = csv.reader(StringIO(content), delimiter=';')
        for line_num, parts in enumerate(reader, 1):
            raw_line = ';'.join(parts).strip()
            if not raw_line or raw_line.startswith('#'):
                continue

            parts = [part.strip() for part in parts]
            if parts and parts[0].strip().lower() in IMPORT_HEADER_NAMES:
                continue

            # Supported formats:
            # 5 columns: english;russian;example_en;example_ru;level
            # 11 columns: + topic;ipa;synonyms;antonyms;frequency_band;etymology
            # 12 columns: + topic_ru;topic_en;ipa;synonyms;antonyms;frequency_band;etymology
            supported_column_counts = (
                IMPORT_BASE_COLUMNS,
                IMPORT_ENRICHED_COLUMNS,
                IMPORT_BILINGUAL_TOPIC_COLUMNS,
            )
            if len(parts) not in supported_column_counts:
                errors.append({
                    'line_num': line_num,
                    'line': raw_line,
                    'error': (
                        'неверный формат '
                        '(ожидается 5, 11 или 12 частей через ;)'
                    )
                })
                continue

            english_word = parts[0].strip().lower()
            russian_translate = parts[1].strip()
            english_sentence = parts[2].strip()
            russian_sentence = parts[3].strip()
            level = parts[4].strip()

            word_data = {
                'line_num': line_num,
                'english_word': english_word,
                'russian_translate': russian_translate,
                'english_sentence': english_sentence,
                'russian_sentence': russian_sentence,
                'level': level
            }

            if len(parts) in (IMPORT_ENRICHED_COLUMNS, IMPORT_BILINGUAL_TOPIC_COLUMNS):
                if len(parts) == IMPORT_BILINGUAL_TOPIC_COLUMNS:
                    topic_ru = parts[5].strip()
                    topic_en = parts[6].strip()
                    topic = WordManagementService._build_topic_name(topic_ru, topic_en)
                    ipa_index = 7
                    synonyms_index = 8
                    antonyms_index = 9
                    frequency_band_index = 10
                    etymology_index = 11
                else:
                    topic_ru = None
                    topic_en = None
                    topic = parts[5].strip() or None
                    ipa_index = 6
                    synonyms_index = 7
                    antonyms_index = 8
                    frequency_band_index = 9
                    etymology_index = 10

                frequency_band_raw = parts[frequency_band_index].strip()
                frequency_band = WordManagementService._parse_frequency_band(
                    frequency_band_raw
                )
                if frequency_band_raw and frequency_band is None:
                    errors.append({
                        'line_num': line_num,
                        'line': raw_line,
                        'error': (
                            'неверный frequency_band '
                            '(используйте high/medium/low или 1/2/3)'
                        )
                    })
                    continue

                word_data.update({
                    'topic': topic,
                    'topic_ru': topic_ru,
                    'topic_en': topic_en,
                    'ipa_transcription': WordManagementService._normalize_ipa(parts[ipa_index]),
                    'synonyms': WordManagementService._parse_list_field(parts[synonyms_index]),
                    'antonyms': WordManagementService._parse_list_field(parts[antonyms_index]),
                    'frequency_band': frequency_band,
                    'etymology': parts[etymology_index].strip() or None,
                    'has_enrichment': True,
                })
            else:
                word_data['has_enrichment'] = False

            parsed_rows.append(word_data)

        # Bulk-resolve existence with one query (chunked for safety on huge files).
        from app.utils.db_utils import chunk_ids

        unique_words = list({row['english_word'] for row in parsed_rows})
        existing_set: set[str] = set()
        for chunk in chunk_ids(unique_words, chunk_size=500):
            rows = (
                db.session.query(CollectionWords.english_word)
                .filter(CollectionWords.english_word.in_(chunk))
                .all()
            )
            existing_set.update(r[0] for r in rows)

        for word_data in parsed_rows:
            if word_data['english_word'] in existing_set:
                existing_words.append(word_data)
            else:
                missing_words.append(word_data)

        return existing_words, missing_words, errors

    @staticmethod
    def import_translations(
        existing_words,
        missing_words,
        words_to_add,
        topic_resolutions=None,
    ):
        """
        Импортирует переводы в базу данных

        Args:
            existing_words: Список существующих слов для обновления
            missing_words: Список отсутствующих слов
            words_to_add: Список line_num слов для добавления
            topic_resolutions: Выборы preview для новых/неоднозначных тем

        Returns:
            tuple: (updated_count: int, added_count: int)
        """
        try:
            from app.utils.db_utils import chunk_ids
            from sqlalchemy.orm import selectinload

            updated_count = 0
            added_count = 0

            # Cache topic index once — avoids ``Topic.query.all()`` per word
            # via ``_get_topic_by_name`` on large imports.
            topic_index = WordManagementService._build_topic_index()

            # Bulk-fetch existing CollectionWords with their topics preloaded.
            existing_keys = list({w['english_word'] for w in existing_words})
            word_by_key: dict[str, CollectionWords] = {}
            for chunk in chunk_ids(existing_keys, chunk_size=500):
                rows = (
                    CollectionWords.query
                    .options(selectinload(CollectionWords.topics))
                    .filter(CollectionWords.english_word.in_(chunk))
                    .all()
                )
                for row in rows:
                    word_by_key[row.english_word] = row

            # Обновляем существующие слова
            for word_data in existing_words:
                word = word_by_key.get(word_data['english_word'])
                if word:
                    word.russian_word = word_data['russian_translate']
                    word.sentences = f"{word_data['english_sentence']}<br>{word_data['russian_sentence']}"
                    word.level = word_data['level']
                    word.listening = get_clean_audio_filename(word_data['english_word'])
                    WordManagementService._apply_enrichment_fields(
                        word,
                        word_data,
                        topic_resolutions=topic_resolutions,
                        topic_index=topic_index,
                    )
                    updated_count += 1

            # Добавляем новые слова (если выбраны)
            words_to_add_set = set(map(str, words_to_add or []))
            for word_data in missing_words:
                if str(word_data['line_num']) in words_to_add_set:
                    english_word_normalized = word_data['english_word'].lower().strip()
                    new_word = CollectionWords(
                        english_word=english_word_normalized,
                        russian_word=word_data['russian_translate'],
                        sentences=f"{word_data['english_sentence']}<br>{word_data['russian_sentence']}",
                        level=word_data['level'],
                        listening=get_clean_audio_filename(english_word_normalized)
                    )
                    db.session.add(new_word)
                    WordManagementService._apply_enrichment_fields(
                        new_word,
                        word_data,
                        topic_resolutions=topic_resolutions,
                        topic_index=topic_index,
                    )
                    added_count += 1

            db.session.flush()

            logger.info(f"Translations imported: {updated_count} updated, {added_count} added")
            return updated_count, added_count

        except IntegrityError as e:
            logger.warning("Duplicate english_word on translation import: %s", e)
            db.session.rollback()
            raise ValueError('duplicate_entry') from e
        except Exception as e:
            logger.error(f"Error importing translations: {str(e)}")
            db.session.rollback()
            raise

    @staticmethod
    def get_phrasal_verb_statistics():
        """
        Получает статистику по фразовым глаголам (теперь из CollectionWords)

        Returns:
            dict: Статистика с total, with_audio, without_audio
        """
        try:
            total = CollectionWords.query.filter_by(item_type='phrasal_verb').count()
            with_audio = CollectionWords.query.filter(
                CollectionWords.item_type == 'phrasal_verb',
                CollectionWords.listening != None,
                CollectionWords.listening != ''
            ).count()

            return {
                'total': total,
                'with_audio': with_audio,
                'without_audio': total - with_audio
            }
        except Exception as e:
            logger.error(f"Error getting phrasal verb statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def parse_phrasal_verbs_file(content):
        """
        Парсит CSV файл с фразовыми глаголами

        Args:
            content: Текстовое содержимое файла

        Returns:
            tuple: (new_verbs: list, existing_verbs: list, errors: list)
        """
        import csv
        from io import StringIO

        new_verbs = []
        existing_verbs = []
        errors = []

        try:
            reader = csv.reader(StringIO(content))
            header = next(reader, None)  # Skip header row

            if not header:
                return [], [], [{'line_num': 1, 'error': 'Файл пустой'}]

            for line_num, row in enumerate(reader, 2):  # Start from 2 (after header)
                if not row or all(cell.strip() == '' for cell in row):
                    continue

                if len(row) < 4:
                    errors.append({
                        'line_num': line_num,
                        'line': ','.join(row),
                        'error': f'Недостаточно полей (ожидается 4, получено {len(row)})'
                    })
                    continue

                phrasal_verb = row[0].strip()
                russian_translate = row[1].strip()
                using = row[2].strip()
                sentence = row[3].strip()

                if not phrasal_verb:
                    errors.append({
                        'line_num': line_num,
                        'line': ','.join(row),
                        'error': 'Пустой фразовый глагол'
                    })
                    continue

                verb_data = {
                    'line_num': line_num,
                    'phrasal_verb': phrasal_verb,
                    'russian_translate': russian_translate,
                    'using': using,
                    'sentence': sentence
                }

                # Check if phrasal verb already exists in CollectionWords
                existing = CollectionWords.query.filter_by(english_word=phrasal_verb).first()
                if existing:
                    existing_verbs.append(verb_data)
                else:
                    new_verbs.append(verb_data)

        except Exception as e:
            errors.append({
                'line_num': 0,
                'line': '',
                'error': f'Ошибка парсинга CSV: {str(e)}'
            })

        return new_verbs, existing_verbs, errors

    @staticmethod
    def import_phrasal_verbs(new_verbs, existing_verbs, update_existing=False):
        """
        Импортирует фразовые глаголы в CollectionWords

        Args:
            new_verbs: Список новых фразовых глаголов
            existing_verbs: Список существующих фразовых глаголов
            update_existing: Обновлять ли существующие записи

        Returns:
            tuple: (added_count: int, updated_count: int)
        """
        try:
            added_count = 0
            updated_count = 0

            # Add new phrasal verbs to CollectionWords
            for verb_data in new_verbs:
                new_word = CollectionWords(
                    english_word=verb_data['phrasal_verb'],
                    russian_word=verb_data['russian_translate'],
                    sentences=verb_data['sentence'],
                    item_type='phrasal_verb',
                    usage_context=verb_data['using'],
                    level='B1'  # Default level for phrasal verbs
                )
                db.session.add(new_word)
                added_count += 1

            # Update existing if requested
            if update_existing:
                for verb_data in existing_verbs:
                    word = CollectionWords.query.filter_by(
                        english_word=verb_data['phrasal_verb']
                    ).first()
                    if word:
                        word.russian_word = verb_data['russian_translate']
                        word.sentences = verb_data['sentence']
                        word.usage_context = verb_data['using']
                        word.item_type = 'phrasal_verb'
                        updated_count += 1

            db.session.flush()

            logger.info(
                f"Phrasal verbs imported: {added_count} added, {updated_count} updated"
            )
            return added_count, updated_count

        except IntegrityError as e:
            logger.warning("Duplicate english_word on phrasal verb import: %s", e)
            db.session.rollback()
            raise ValueError('duplicate_entry') from e
        except Exception as e:
            logger.error(f"Error importing phrasal verbs: {str(e)}")
            db.session.rollback()
            raise
