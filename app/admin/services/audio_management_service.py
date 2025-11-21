# app/admin/services/audio_management_service.py

"""
Сервис для управления аудио файлами (Audio Management Service)
Обрабатывает статистику, обновление статусов загрузки и исправление аудио полей
"""
import logging

from app.words.models import CollectionWords
from app.utils.db import db

logger = logging.getLogger(__name__)


class AudioManagementService:
    """Сервис для управления аудио файлами и их статистикой"""

    @staticmethod
    def get_audio_statistics(media_folder):
        """
        Получает общую статистику по аудио файлам

        Args:
            media_folder: Путь к папке с медиа файлами

        Returns:
            dict: Статистика с ключами: words_total, words_with_audio,
                  words_without_audio, problematic_audio, recent_audio_updates
        """
        try:
            # Статистика по аудио файлам
            words_total = CollectionWords.query.count()

            # Слова с доступным аудио (get_download = 1)
            words_with_audio = CollectionWords.query.filter_by(get_download=1).count()

            # Слова без аудио
            words_without_audio = words_total - words_with_audio

            # Слова с проблемными URL аудио (содержат http)
            problematic_audio = CollectionWords.query.filter(
                CollectionWords.listening.like('http%')
            ).count()

            # Недавно обновленные аудио записи
            recent_audio_updates = CollectionWords.query.filter_by(
                get_download=1
            ).order_by(CollectionWords.id.desc()).limit(10).all()

            return {
                'words_total': words_total,
                'words_with_audio': words_with_audio,
                'words_without_audio': words_without_audio,
                'problematic_audio': problematic_audio,
                'recent_audio_updates': recent_audio_updates,
                'media_folder': media_folder
            }
        except Exception as e:
            logger.error(f"Error getting audio statistics: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def update_download_status(table_name, column_name, media_folder):
        """
        Обновляет статус загрузки аудио файлов

        Args:
            table_name: Имя таблицы
            column_name: Имя колонки с названием слова
            media_folder: Путь к папке с медиа файлами

        Returns:
            int: Количество обновленных записей
        """
        try:
            from app.repository import DatabaseRepository

            # Обновляем статус загрузки
            repo = DatabaseRepository()
            updated_count = repo.update_download_status(table_name, column_name, media_folder)

            logger.info(f"Audio download status updated: {updated_count} records")
            return updated_count

        except Exception as e:
            logger.error(f"Error updating audio download status: {str(e)}")
            raise

    @staticmethod
    def fix_listening_fields():
        """
        Исправляет поля прослушивания (listening) для слов

        Returns:
            tuple: (success: bool, fixed_count: int, message: str)
        """
        try:
            # Находим слова, требующие исправления
            words_to_fix = CollectionWords.query.filter(
                CollectionWords.russian_word.isnot(None),
                CollectionWords.english_word.isnot(None),
                CollectionWords.english_word != '',
                CollectionWords.listening.like('http%')
            ).all()

            if not words_to_fix:
                return True, 0, 'Нет записей, требующих исправления'

            # Исправляем поля listening
            count = 0
            try:
                from app.audio.manager import AudioManager
                audio_manager = AudioManager()

                for word in words_to_fix:
                    try:
                        listening = audio_manager.update_anki_field_format(word.english_word)
                        word.listening = listening
                        count += 1
                    except Exception as e:
                        logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                        continue

            except ImportError:
                # Если модуль AudioManager недоступен, используем простую замену
                for word in words_to_fix:
                    try:
                        word.listening = f"[sound:pronunciation_en_{word.english_word}.mp3]"
                        count += 1
                    except Exception as e:
                        logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                        continue

            # Сохраняем изменения
            db.session.commit()

            logger.info(f"Audio listening fields fixed: {count} records")
            return True, count, f'Исправлено полей listening: {count}'

        except Exception as e:
            logger.error(f"Error fixing listening fields: {str(e)}")
            db.session.rollback()
            return False, 0, str(e)

    @staticmethod
    def get_download_list(pattern=None):
        """
        Получает список слов для загрузки аудио

        Args:
            pattern: Паттерн для фильтрации слов (опционально)

        Returns:
            list: Список английских слов без аудио
        """
        try:
            from config.settings import COLLECTIONS_TABLE
            from app.repository import DatabaseRepository

            # Формируем запрос
            repo = DatabaseRepository()
            query = f"""
                SELECT english_word FROM {COLLECTIONS_TABLE}
                WHERE russian_word IS NOT NULL AND (get_download = 0 OR get_download IS NULL)
            """

            params = []
            if pattern:
                query += " AND english_word LIKE %s"
                params.append(f"{pattern}%")

            query += " ORDER BY english_word"

            result = repo.execute_query(query, params, fetch=True)

            if not result:
                return []

            # Получаем список слов
            words = [row[0] for row in result if row and len(row) > 0]
            return words

        except Exception as e:
            logger.error(f"Error getting download list: {str(e)}")
            return []

    @staticmethod
    def get_detailed_statistics():
        """
        Получает детальную статистику по аудио для страницы статистики

        Returns:
            dict: Детальная статистика с разбивкой по статусам загрузки,
                  форматам listening и уровням
        """
        try:
            from config.settings import COLLECTIONS_TABLE
            from app.repository import DatabaseRepository

            repo = DatabaseRepository()

            # Статистика по статусу загрузки
            download_stats_raw = repo.execute_query(f"""
                SELECT
                    CASE
                        WHEN get_download = 1 THEN 'Available'
                        WHEN get_download = 0 THEN 'Not Available'
                        ELSE 'Unknown'
                    END as status,
                    COUNT(*) as count
                FROM {COLLECTIONS_TABLE}
                GROUP BY get_download
                ORDER BY get_download DESC
            """, fetch=True)

            # Преобразуем в словари
            download_stats = []
            for row in download_stats_raw or []:
                if row and len(row) >= 2:
                    download_stats.append({
                        'status': row[0],
                        'count': row[1]
                    })

            # Статистика по форматам listening
            listening_stats_raw = repo.execute_query(f"""
                SELECT
                    CASE
                        WHEN listening LIKE 'http%%' THEN 'HTTP URL'
                        WHEN listening LIKE '[sound:%%' THEN 'Anki Format'
                        WHEN listening IS NULL OR listening = '' THEN 'Empty'
                        ELSE 'Other Format'
                    END as format_type,
                    COUNT(*) as row_count
                FROM collection_words
                GROUP BY
                    CASE
                        WHEN listening LIKE 'http%%' THEN 'HTTP URL'
                        WHEN listening LIKE '[sound:%%' THEN 'Anki Format'
                        WHEN listening IS NULL OR listening = '' THEN 'Empty'
                        ELSE 'Other Format'
                    END
                ORDER BY row_count DESC""", fetch=True)

            # Преобразуем в словари
            listening_stats = []
            for row in listening_stats_raw or []:
                if row and len(row) >= 2:
                    listening_stats.append({
                        'format_type': row[0],
                        'count': row[1]
                    })

            # Слова по уровням с аудио
            level_audio_stats_raw = repo.execute_query(f"""
                SELECT
                    COALESCE(level, 'Unknown') as level,
                    COUNT(*) as words_total,
                    SUM(CASE WHEN get_download = 1 THEN 1 ELSE 0 END) as with_audio
                FROM {COLLECTIONS_TABLE}
                GROUP BY level
                ORDER BY level
            """, fetch=True)

            # Преобразуем в словари
            level_audio_stats = []
            for row in level_audio_stats_raw or []:
                if row and len(row) >= 3:
                    level_audio_stats.append({
                        'level': row[0],
                        'words_total': row[1],
                        'with_audio': row[2]
                    })

            return {
                'download_stats': download_stats,
                'listening_stats': listening_stats,
                'level_audio_stats': level_audio_stats
            }

        except Exception as e:
            logger.error(f"Error getting detailed audio statistics: {str(e)}")
            return {'error': str(e)}
