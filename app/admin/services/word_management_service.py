# app/admin/services/word_management_service.py

"""
Сервис для управления словами (Word Management Service)
Обрабатывает импорт, экспорт, массовые обновления и статистику слов
"""
import logging
from sqlalchemy import func

from app.auth.models import User
from app.books.models import Book
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


class WordManagementService:
    """Сервис для управления словами и их статистикой"""

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
        Массово обновляет статус слов для пользователей

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

            # Если не указан пользователь, обновляем для всех активных
            if not user_id:
                active_users = User.query.filter_by(active=True).all()
                user_ids = [user.id for user in active_users]
            else:
                user_ids = [user_id]

            updated_count = 0

            for word_text in words:
                # Найти слово в базе
                word = CollectionWords.query.filter_by(
                    english_word=word_text.lower().strip()
                ).first()

                if word:
                    for uid in user_ids:
                        user = User.query.get(uid)
                        if user:
                            user.set_word_status(word.id, status)
                            updated_count += 1

            db.session.commit()
            total_requested = len(words) * len(user_ids)

            logger.info(f"Bulk status update: {updated_count} words updated to '{status}'")
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
        """
        lines = content.strip().split('\n')
        existing_words = []
        missing_words = []
        errors = []

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Ожидаем формат: english_word;russian_translate;english_sentence;russian_sentence;level
            parts = line.split(';')
            if len(parts) != 5:
                errors.append({
                    'line_num': line_num,
                    'line': line,
                    'error': 'неверный формат (ожидается 5 частей через ;)'
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

            # Найти слово в базе
            word = CollectionWords.query.filter_by(english_word=english_word).first()
            if word:
                existing_words.append(word_data)
            else:
                missing_words.append(word_data)

        return existing_words, missing_words, errors

    @staticmethod
    def import_translations(existing_words, missing_words, words_to_add):
        """
        Импортирует переводы в базу данных

        Args:
            existing_words: Список существующих слов для обновления
            missing_words: Список отсутствующих слов
            words_to_add: Список line_num слов для добавления

        Returns:
            tuple: (updated_count: int, added_count: int)
        """
        try:
            updated_count = 0
            added_count = 0

            # Обновляем существующие слова
            for word_data in existing_words:
                word = CollectionWords.query.filter_by(
                    english_word=word_data['english_word']
                ).first()
                if word:
                    word.russian_word = word_data['russian_translate']
                    word.sentences = f"{word_data['english_sentence']}<br>{word_data['russian_sentence']}"
                    word.level = word_data['level']
                    word.listening = f"[sound:pronunciation_en_{word_data['english_word'].replace(' ', '_').lower()}.mp3]"
                    updated_count += 1

            # Добавляем новые слова (если выбраны)
            for word_data in missing_words:
                if str(word_data['line_num']) in words_to_add:
                    english_word_normalized = word_data['english_word'].lower().strip()
                    new_word = CollectionWords(
                        english_word=english_word_normalized,
                        russian_word=word_data['russian_translate'],
                        sentences=f"{word_data['english_sentence']}<br>{word_data['russian_sentence']}",
                        level=word_data['level'],
                        listening=f"[sound:pronunciation_en_{english_word_normalized.replace(' ', '_')}.mp3]"
                    )
                    db.session.add(new_word)
                    added_count += 1

            db.session.commit()

            logger.info(f"Translations imported: {updated_count} updated, {added_count} added")
            return updated_count, added_count

        except Exception as e:
            logger.error(f"Error importing translations: {str(e)}")
            db.session.rollback()
            raise
