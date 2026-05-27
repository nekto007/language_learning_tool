# app/admin/services/audio_management_service.py

"""
Сервис для управления аудио файлами (Audio Management Service)
Обрабатывает статистику, обновление статусов загрузки и исправление аудио полей
"""
import logging
import os
import re

from app.words.models import CollectionWords
from app.utils.audio import get_clean_audio_filename
from app.utils.db import db

logger = logging.getLogger(__name__)

# Batch size for streaming bulk DB fixes — partial commits survive mid-loop failures.
BULK_COMMIT_BATCH_SIZE = 200

# Filename safety: allow only the characters our pipeline actually produces.
_SAFE_AUDIO_FILENAME_RE = re.compile(r'^[A-Za-z0-9._-]+\.mp3$')
_UNSAFE_WORD_CHARS_RE = re.compile(r'[^a-z0-9_-]+')


def safe_audio_filename(filename):
    """Return ``filename`` only if it is a plain mp3 basename — else None.

    Rejects anything containing path separators, parent-traversal segments,
    null bytes, leading dots, or characters outside ``[A-Za-z0-9._-]``. The
    file must end with ``.mp3`` so the helper cannot be misused to allow
    arbitrary extensions.
    """
    if not filename or not isinstance(filename, str):
        return None
    name = filename.strip()
    if not name or '\x00' in name:
        return None
    if name != os.path.basename(name):
        return None
    if name.startswith('.') or '..' in name:
        return None
    if not _SAFE_AUDIO_FILENAME_RE.match(name):
        return None
    return name


def safe_audio_path(media_folder, filename):
    """Return absolute path inside ``media_folder`` or None when unsafe.

    Combines :func:`safe_audio_filename` with realpath containment so callers
    cannot read or delete files outside the configured media root even if a
    legacy DB row carries crafted ``listening`` text.
    """
    safe_name = safe_audio_filename(filename)
    if safe_name is None or not media_folder:
        return None
    media_root = os.path.realpath(media_folder)
    candidate = os.path.realpath(os.path.join(media_root, safe_name))
    if os.path.commonpath([media_root, candidate]) != media_root:
        return None
    return candidate


def safe_audio_filename_for_word(english_word):
    """Generate ``pronunciation_en_<slug>.mp3`` with traversal-safe slug.

    Lowercases, replaces spaces with underscores, then strips every character
    outside ``[a-z0-9_-]``. Returns None if the slug collapses to empty so the
    caller never persists a junk filename.
    """
    if not english_word or not isinstance(english_word, str):
        return None
    slug = english_word.strip().lower().replace(' ', '_')
    slug = _UNSAFE_WORD_CHARS_RE.sub('', slug)
    if not slug:
        return None
    return f"pronunciation_en_{slug}.mp3"


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
        from config.settings import COLLECTIONS_TABLE
        from sqlalchemy import or_

        try:
            if table_name == COLLECTIONS_TABLE and column_name == 'english_word':
                # ORM path: no commit inside — caller's db.session.commit() covers
                # both this mutation and the AdminAuditLog row atomically.
                words = CollectionWords.query.filter(
                    or_(
                        CollectionWords.get_download.is_(None),
                        CollectionWords.get_download != 1,
                    )
                ).all()

                updated_count = 0
                for word in words:
                    try:
                        existing = word.listening or ''
                        if (existing
                                and not existing.startswith('http')
                                and not existing.startswith('[sound:')):
                            # The listening field is already a clean filename. Also try the
                            # legacy name as a fallback: safe_audio_filename_for_word strips
                            # punctuation (can't → cant), but the actual file may have been
                            # produced by get_clean_audio_filename which keeps apostrophes.
                            legacy_name = get_clean_audio_filename(word.english_word)
                            candidates = list(dict.fromkeys(
                                n for n in [existing, legacy_name] if n
                            ))
                            filename = next(
                                (c for c in candidates
                                 if os.path.isfile(os.path.join(media_folder, c))),
                                None,
                            )
                            if not filename:
                                continue
                        else:
                            safe_name = safe_audio_filename_for_word(word.english_word)
                            if not safe_name:
                                continue
                            # Fall back to legacy format (keeps apostrophes/hyphens) so
                            # existing files produced by get_clean_audio_filename are found.
                            legacy_name = get_clean_audio_filename(word.english_word)
                            candidates = list(dict.fromkeys(
                                n for n in [safe_name, legacy_name] if n
                            ))
                            filename = next(
                                (c for c in candidates
                                 if os.path.isfile(os.path.join(media_folder, c))),
                                None,
                            )
                            if not filename:
                                continue

                        full_path = os.path.join(media_folder, filename)
                        if os.path.isfile(full_path):
                            word.get_download = 1
                            word.listening = filename
                            updated_count += 1
                    except Exception as e:
                        logger.warning('Error checking audio for word id=%s: %s',
                                       getattr(word, 'id', '?'), e)
                        continue

                logger.info('Audio download status updated (ORM): %d records', updated_count)
                return updated_count
            else:
                # Legacy psycopg2 path for non-collection_words tables.
                from app.repository import DatabaseRepository
                repo = DatabaseRepository()
                updated_count = repo.update_download_status(table_name, column_name, media_folder)
                logger.info('Audio download status updated (psycopg2): %d records', updated_count)
                return updated_count

        except Exception as e:
            logger.error(f"Error updating audio download status: {str(e)}")
            raise

    # Backward-compatible alias — kept for old call-sites; new code should use
    # safe_audio_filename_for_word which sanitises the slug.
    _get_clean_audio_filename = staticmethod(get_clean_audio_filename)

    @staticmethod
    def fix_listening_fields():
        """
        Исправляет поля прослушивания (listening) для слов с HTTP URL.
        Сохраняет чистое имя файла (pronunciation_en_word.mp3) без обертки [sound:...].
        Формат [sound:...] добавляется только при экспорте в Anki.

        Returns:
            tuple: (success: bool, fixed_count: int, message: str)
        """
        try:
            # Находим слова с HTTP URL, требующие исправления
            words_to_fix = CollectionWords.query.filter(
                CollectionWords.russian_word.isnot(None),
                CollectionWords.english_word.isnot(None),
                CollectionWords.english_word != '',
                CollectionWords.listening.like('http%')
            ).all()

            if not words_to_fix:
                return True, 0, 'Нет записей с HTTP URL, требующих исправления'

            # Исправляем поля listening - сохраняем чистое имя файла.
            # Коммитим батчами, чтобы частичный сбой не откатил всю работу.
            count = 0
            for word in words_to_fix:
                try:
                    safe_name = safe_audio_filename_for_word(word.english_word)
                    if safe_name is None:
                        logger.warning(
                            "Skipping unsafe english_word in fix_listening_fields: id=%s",
                            word.id,
                        )
                        continue
                    word.listening = safe_name
                    count += 1
                    if count % BULK_COMMIT_BATCH_SIZE == 0:
                        db.session.commit()
                except Exception as e:
                    logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                    continue

            # Финальный коммит для остатка батча
            db.session.commit()

            logger.info(f"Audio listening fields fixed (HTTP->clean): {count} records")
            return True, count, f'Исправлено полей listening (HTTP→чистый формат): {count}'

        except Exception as e:
            logger.error(f"Error fixing listening fields: {str(e)}")
            db.session.rollback()
            return False, 0, str(e)

    @staticmethod
    def normalize_listening_fields():
        """
        Нормализует поля listening: убирает обертку [sound:...] и оставляет чистое имя файла.
        Это позволяет использовать аудио напрямую в приложении, а формат [sound:...]
        добавлять только при экспорте в Anki.

        Returns:
            tuple: (success: bool, fixed_count: int, message: str)
        """
        import re
        try:
            # Находим слова с форматом [sound:...]
            words_to_fix = CollectionWords.query.filter(
                CollectionWords.listening.like('[sound:%')
            ).all()

            if not words_to_fix:
                return True, 0, 'Нет записей с форматом [sound:...], требующих нормализации'

            count = 0
            for word in words_to_fix:
                try:
                    # Извлекаем чистое имя файла из [sound:filename.mp3]
                    match = re.search(r'\[sound:([^\]]+)\]', word.listening)
                    if match:
                        candidate = match.group(1).strip()
                        safe_name = safe_audio_filename(candidate)
                        if safe_name is None:
                            logger.warning(
                                "Skipping unsafe [sound:] payload for word id=%s",
                                word.id,
                            )
                            continue
                        word.listening = safe_name
                        count += 1
                        if count % BULK_COMMIT_BATCH_SIZE == 0:
                            db.session.commit()
                except Exception as e:
                    logger.warning(f"Error normalizing word {word.english_word}: {str(e)}")
                    continue

            db.session.commit()

            logger.info(f"Audio listening fields normalized: {count} records")
            return True, count, f'Нормализовано полей listening ([sound:]→чистый формат): {count}'

        except Exception as e:
            logger.error(f"Error normalizing listening fields: {str(e)}")
            db.session.rollback()
            return False, 0, str(e)

    @staticmethod
    def fill_empty_listening_fields():
        """
        Заполняет пустые (NULL или '') поля listening чистым именем файла.
        Генерирует pronunciation_en_word.mp3 на основе english_word.

        Returns:
            tuple: (success: bool, fixed_count: int, message: str)
        """
        try:
            from sqlalchemy import or_

            words_to_fix = CollectionWords.query.filter(
                CollectionWords.russian_word.isnot(None),
                CollectionWords.english_word.isnot(None),
                CollectionWords.english_word != '',
                or_(
                    CollectionWords.listening.is_(None),
                    CollectionWords.listening == ''
                )
            ).all()

            if not words_to_fix:
                return True, 0, 'Нет записей с пустым полем listening'

            count = 0
            for word in words_to_fix:
                try:
                    safe_name = safe_audio_filename_for_word(word.english_word)
                    if safe_name is None:
                        logger.warning(
                            "Skipping unsafe english_word in fill_empty_listening: id=%s",
                            word.id,
                        )
                        continue
                    word.listening = safe_name
                    count += 1
                    if count % BULK_COMMIT_BATCH_SIZE == 0:
                        db.session.commit()
                except Exception as e:
                    logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                    continue

            db.session.commit()

            logger.info(f"Empty listening fields filled: {count} records")
            return True, count, f'Заполнено пустых полей listening: {count}'

        except Exception as e:
            logger.error(f"Error filling empty listening fields: {str(e)}")
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
                        WHEN listening LIKE 'pronunciation_en_%%' THEN 'Clean Filename'
                        ELSE 'Other Format'
                    END as format_type,
                    COUNT(*) as row_count
                FROM collection_words
                GROUP BY
                    CASE
                        WHEN listening LIKE 'http%%' THEN 'HTTP URL'
                        WHEN listening LIKE '[sound:%%' THEN 'Anki Format'
                        WHEN listening IS NULL OR listening = '' THEN 'Empty'
                        WHEN listening LIKE 'pronunciation_en_%%' THEN 'Clean Filename'
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

    @staticmethod
    def _collect_referenced_filenames():
        """Return a set of clean mp3 basenames currently referenced by DB rows."""
        from app.utils.audio import parse_audio_filename

        referenced = set()
        rows = (
            db.session.query(CollectionWords.listening)
            .filter(CollectionWords.listening.isnot(None))
            .filter(CollectionWords.listening != '')
            .all()
        )
        for (raw,) in rows:
            name = parse_audio_filename(raw)
            if not name:
                continue
            safe_name = safe_audio_filename(name)
            if safe_name is not None:
                referenced.add(safe_name)
        return referenced

    @staticmethod
    def find_orphan_audio_files(media_folder, limit=None):
        """List mp3 files in ``media_folder`` not referenced by any DB row.

        Refuses to scan when ``media_folder`` is missing or not a directory.
        Skips filenames that fail :func:`safe_audio_filename` so traversal
        artefacts in the folder cannot leak into the response. ``limit`` caps
        the returned list (None = unlimited).

        Returns: dict ``{folder, total_files, referenced, orphan_count,
        orphans: [filename, ...]}`` — or ``{'error': str}``.
        """
        try:
            if not media_folder or not os.path.isdir(media_folder):
                return {'error': 'media_folder does not exist'}

            referenced = AudioManagementService._collect_referenced_filenames()

            orphans = []
            total = 0
            total_orphans = 0
            for entry in os.listdir(media_folder):
                if not entry.lower().endswith('.mp3'):
                    continue
                safe_name = safe_audio_filename(entry)
                if safe_name is None:
                    continue
                total += 1
                if safe_name in referenced:
                    continue
                total_orphans += 1
                if limit is None or len(orphans) < limit:
                    orphans.append(safe_name)

            orphans.sort()
            return {
                'folder': media_folder,
                'total_files': total,
                'referenced': len(referenced),
                'orphan_count': total_orphans,
                'orphans': orphans,
            }
        except OSError as e:
            logger.error(f"Error scanning media folder for orphans: {e}")
            return {'error': str(e)}

    @staticmethod
    def clear_audio_references(filename: str, db_session) -> int:
        """Nullify Chapter.audio_url rows that reference ``filename``.

        Call before (or after) deleting a referenced audio file so that the
        DB is not left pointing at a missing path. Returns the count of rows
        updated; does NOT commit — caller is responsible for the commit.
        """
        safe_name = safe_audio_filename(filename)
        if safe_name is None:
            return 0
        from app.books.models import Chapter
        updated = (
            db_session.query(Chapter)
            .filter(Chapter.audio_url.ilike(f'%{safe_name}'))
            .all()
        )
        count = 0
        for chapter in updated:
            chapter.audio_url = None
            count += 1
        return count

    @staticmethod
    def delete_orphan_audio_files(media_folder, dry_run=True):
        """Delete orphan mp3 files inside ``media_folder``.

        Path containment is enforced per-file via :func:`safe_audio_path`;
        anything that cannot be resolved inside ``media_folder`` is skipped
        and counted in ``skipped``. When ``dry_run`` is True (default) the
        method only enumerates orphans — no deletion happens.

        Returns: dict ``{dry_run, deleted, skipped, errors, orphans}`` — or
        ``{'error': str}`` on top-level failure.
        """
        scan = AudioManagementService.find_orphan_audio_files(media_folder)
        if 'error' in scan:
            return scan

        orphans = scan['orphans']
        if dry_run:
            return {
                'dry_run': True,
                'deleted': 0,
                'skipped': 0,
                'errors': [],
                'orphans': orphans,
            }

        deleted = 0
        skipped = 0
        errors = []
        for name in orphans:
            full_path = safe_audio_path(media_folder, name)
            if full_path is None:
                skipped += 1
                continue
            try:
                os.remove(full_path)
                deleted += 1
            except OSError as e:
                errors.append({'file': name, 'error': str(e)})
                logger.warning(f"Failed to delete orphan audio {name}: {e}")

        return {
            'dry_run': False,
            'deleted': deleted,
            'skipped': skipped,
            'errors': errors,
            'orphans': orphans,
        }
