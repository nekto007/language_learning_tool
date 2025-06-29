# app/books/processors.py

import contextlib
import logging
import queue
import threading
import time
from typing import Dict, List

from bs4 import BeautifulSoup

from app.books.models import Book, Block, BlockVocab
from app.words.models import CollectionWords
from app.nlp.processor import prepare_word_data, process_text
from app.nlp.setup import download_nltk_resources, initialize_nltk
from app.repository import DatabaseRepository
from app.utils.db import db
from sqlalchemy import func, desc, text
from config.settings import (
    MAX_CONCURRENT_PROCESSING, MAX_PROCESSING_TIME, MAX_STATUS_AGE, MAX_SYNC_PROCESSING_SIZE, STATUS_CLEANUP_INTERVAL,
    SYNC_PROCESSING_TIMEOUT,
)

logger = logging.getLogger(__name__)

processing_queue = queue.Queue()
processing_status = {}
worker_running = False
processing_semaphore = threading.Semaphore(MAX_CONCURRENT_PROCESSING)
cleanup_timer = None

flask_app = None


def get_app():
    """
    Получает экземпляр Flask-приложения

    Returns:
        Flask app: Экземпляр Flask-приложения
    """
    global flask_app
    if flask_app is None:
        # Пробуем получить текущее приложение, если оно уже создано
        from flask import current_app
        try:
            # Если мы в контексте приложения, используем его
            flask_app = current_app._get_current_object()
            logger.debug("Using existing Flask app from current_app")
        except RuntimeError:
            # Если нет контекста приложения, создаем новое
            logger.warning("No Flask app context found, creating new app instance")
            from app import create_app
            flask_app = create_app()
    return flask_app


def extract_words_from_html_content(html_content: str) -> List[str]:
    """
    Извлекает слова из HTML-контента книги.
    Оптимизировано для больших книг с контролем памяти.

    Args:
        html_content (str): HTML-контент книги

    Returns:
        List[str]: Список обработанных слов
    """
    try:
        # Загружаем ресурсы NLTK
        download_nltk_resources()
        english_vocab, brown_words, stop_words = initialize_nltk()

        # Извлекаем текст порциями, если контент большой
        chunk_size = 300000  # Примерно 300KB на чанк (увеличено для больших книг)
        all_words = []

        if len(html_content) > chunk_size * 3:  # Если книга очень большая (>600KB)
            logger.info(f"Большой HTML контент ({len(html_content)} байт), обрабатываем по частям")

            # Используем BeautifulSoup для разбиения на параграфы
            soup = BeautifulSoup(html_content, "html.parser")
            paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div'])

            # Обрабатываем параграфы группами
            current_chunk = ""
            for paragraph in paragraphs:
                paragraph_text = paragraph.get_text()

                # Если добавление этого параграфа превысит размер чанка, обрабатываем текущий чанк
                if len(current_chunk) + len(paragraph_text) > chunk_size:
                    # Обрабатываем текущий чанк, если он не пустой
                    if current_chunk.strip():
                        words = process_text(current_chunk, english_vocab, stop_words)
                        all_words.extend(words)

                    # Начинаем новый чанк с текущего параграфа
                    current_chunk = paragraph_text

                    # Принудительная сборка мусора для освобождения памяти
                    import gc
                    gc.collect()
                else:
                    # Добавляем параграф к текущему чанку
                    if current_chunk:
                        current_chunk += " " + paragraph_text
                    else:
                        current_chunk = paragraph_text

            # Обрабатываем последний чанк, если он не пустой
            if current_chunk.strip():
                words = process_text(current_chunk, english_vocab, stop_words)
                all_words.extend(words)
        else:
            # Для небольших книг обрабатываем весь текст сразу
            soup = BeautifulSoup(html_content, "html.parser")
            text = soup.get_text()

            # Проверяем, что текст не пустой
            if not text or len(text.strip()) < 10:
                logger.warning("HTML-контент не содержит текста или слишком короткий для обработки")
                return []

            # Обрабатываем текст
            all_words = process_text(text, english_vocab, stop_words)

        # Очистка памяти перед возвратом результата
        import gc
        gc.collect()

        return all_words
    except Exception as e:
        logger.error(f"Ошибка при извлечении слов из HTML-контента: {str(e)}")
        return []


def process_book_words(book_id: int, html_content: str) -> Dict:
    """
    Обрабатывает слова из книги, создает связи слово-книга и обновляет статистику.
    Оптимизировано для больших книг с контролем памяти.

    Args:
        book_id (int): ID книги
        html_content (str): HTML-контент книги

    Returns:
        Dict: Статистика об обработанных словах
    """
    try:
        # Проверяем, есть ли уже контекст приложения
        from flask import has_app_context
        
        if has_app_context():
            # Если контекст уже есть, работаем напрямую
            return _process_book_words_internal(book_id, html_content)
        else:
            # Если контекста нет, получаем приложение и создаем контекст
            app = get_app()
            with app.app_context():
                return _process_book_words_internal(book_id, html_content)
                
    except Exception as e:
        logger.error(f"Ошибка при обработке слов для книги ID {book_id}: {str(e)}")
        return {"status": "error", "message": str(e)}


def _process_book_words_internal(book_id: int, html_content: str) -> Dict:
    """
    Внутренняя функция обработки слов из книги.
    Должна вызываться только внутри контекста приложения.
    
    Args:
        book_id (int): ID книги
        html_content (str): HTML-контент книги
        
    Returns:
        Dict: Статистика об обработанных словах
    """
    # Приобретаем семафор для ограничения числа одновременных обработок
    with contextlib.ExitStack() as stack:
        acquired = processing_semaphore.acquire(timeout=5)
        if acquired:
            stack.callback(processing_semaphore.release)
        else:
            logger.warning(
                f"Не удалось получить разрешение для обработки книги ID {book_id} - слишком много одновременных задач")
            return {"status": "error", "message": "Too many concurrent processing tasks"}

        start_time = time.time()
        logger.info(f"Начало обработки слов для книги ID {book_id}")

        # Проверяем существование книги (теперь в контексте приложения)
        try:
            book = Book.query.get(book_id)
            if not book:
                return {"status": "error", "message": f"Book with ID {book_id} not found"}
        except Exception as db_err:
            logger.error(f"Ошибка при проверке существования книги {book_id}: {str(db_err)}")
            return {"status": "error", "message": f"Database error: {str(db_err)}"}

        # Извлекаем слова из контента с оптимизированной функцией
        all_words = extract_words_from_html_content(html_content)

        if not all_words:
            logger.warning(f"Не удалось извлечь слова из книги ID {book_id}")
            return {"status": "error", "message": "No words extracted"}

        # Получаем статистику
        total_words = len(all_words)
        unique_words = len(set(all_words))

        logger.info(f"Извлечено {total_words} слов, {unique_words} уникальных для книги ID {book_id}")

        # Инициализация NLTK ресурсов
        download_nltk_resources()
        _, brown_words, _ = initialize_nltk()

        # Подготовка данных для вставки с обработкой по частям
        # Разбиваем слова на группы по 5000 для обработки
        batch_size = 5000
        total_added = 0

        for i in range(0, len(all_words), batch_size):
            batch = all_words[i:i + batch_size]
            word_data_batch = prepare_word_data(batch, brown_words)

            # Создание репозитория для работы с БД
            repo = DatabaseRepository()

            # Обрабатываем пакет слов
            batch_added = repo.process_batch_from_original_format(word_data_batch, book_id, batch_size=500)
            total_added += batch_added

            # Обновляем статус
            processed_percent = min(100, int((i + len(batch)) / len(all_words) * 100))
            processing_status[book_id] = {
                **processing_status.get(book_id, {}),
                "status": "processing",
                "progress": processed_percent,
                "message": f"Processing words: {processed_percent}% complete",
                "words_processed_so_far": total_added
            }

            # Принудительная сборка мусора
            import gc
            gc.collect()

        # Обновляем статистику книги в конце
        repo = DatabaseRepository()
        repo.update_book_stats(book_id, total_words, unique_words)

        # Заполняем block_vocab если есть блоки
        block_vocab_result = populate_block_vocab(book_id)

        elapsed_time = time.time() - start_time
        logger.info(
            f"Завершена обработка {total_added} слов для книги ID {book_id} за {elapsed_time:.2f} секунд")

        return {
            "status": "success",
            "total_words": total_words,
            "unique_words": unique_words,
            "words_added": total_added,
            "block_vocab_populated": block_vocab_result.get("blocks_updated", 0),
            "elapsed_time": elapsed_time
        }


def enqueue_book_processing(book_id: int, html_content: str) -> Dict:
    """
    Ставит задачу по обработке книги в очередь или обрабатывает небольшие книги синхронно

    Args:
        book_id (int): ID книги
        html_content (str): HTML-контент книги

    Returns:
        Dict: Информация о статусе постановки в очередь
    """
    global worker_running, cleanup_timer

    # Проверяем, не была ли уже запущена обработка для этой книги
    if book_id in processing_status:
        current_status = processing_status[book_id].get("status")
        if current_status in ["processing"]:
            return {
                "status": "already_processing",
                "book_id": book_id,
                "message": "Book is already being processed"
            }

    # Для небольших книг делаем синхронную обработку с таймаутом
    content_size = len(html_content)
    if content_size <= MAX_SYNC_PROCESSING_SIZE:
        logger.info(f"Небольшая книга ID {book_id} (размер: {content_size}) - обрабатываем синхронно")

        # Обновляем статус
        processing_status[book_id] = {
            "status": "processing",
            "started_at": time.time(),
            "message": "Book processing started"
        }

        # Запускаем обработку в отдельном потоке с таймаутом
        result = {"status": "timeout", "message": f"Processing timed out after {SYNC_PROCESSING_TIMEOUT} seconds"}

        def process_with_timeout():
            nonlocal result
            result = process_book_words(book_id, html_content)

        processing_thread = threading.Thread(target=process_with_timeout)
        processing_thread.daemon = True
        processing_thread.start()
        processing_thread.join(SYNC_PROCESSING_TIMEOUT)

        # Обновляем статус с результатом
        processing_status[book_id] = {
            **processing_status.get(book_id, {}),
            **result,
            "completed_at": time.time()
        }

        return {
            "status": result["status"],
            "book_id": book_id,
            "message": result.get("message", "Book processing completed"),
            "sync": True
        }

    # Для больших книг используем асинхронную обработку через очередь
    # Добавляем задачу в очередь
    processing_queue.put((book_id, html_content))

    # Обновляем статус обработки
    processing_status[book_id] = {
        "status": "queued",
        "queued_at": time.time(),
        "message": "Book processing has been queued",
        "book_size": content_size
    }

    # Запускаем обработчик, если он не запущен
    if not worker_running:
        worker_thread = threading.Thread(target=book_processing_worker)
        worker_thread.daemon = True  # Поток будет автоматически завершен при завершении основного приложения
        worker_thread.start()
        worker_running = True

    # Запускаем таймер очистки старых записей, если он не запущен
    if cleanup_timer is None or not cleanup_timer.is_alive():
        cleanup_timer = threading.Timer(STATUS_CLEANUP_INTERVAL, lambda: cleanup_old_statuses(MAX_STATUS_AGE))
        cleanup_timer.daemon = True
        cleanup_timer.start()

    return {
        "status": "queued",
        "book_id": book_id,
        "message": "Book processing has been queued",
        "async": True
    }


def get_processing_status(book_id: int) -> Dict:
    """
    Возвращает текущий статус обработки книги

    Args:
        book_id (int): ID книги

    Returns:
        Dict: Информация о статусе обработки
    """
    if book_id in processing_status:
        return processing_status[book_id]
    else:
        return {"status": "unknown", "message": "No processing record found for this book"}


def book_processing_worker():
    """
    Фоновый поток для обработки книг из очереди
    """
    global worker_running

    logger.info("Запущен обработчик книг")
    idle_count = 0  # Счетчик холостых циклов

    # Получаем приложение Flask
    app = get_app()

    try:
        while True:
            try:
                # Проверяем, есть ли задачи в очереди
                if processing_queue.empty():
                    # Если очередь пуста, ждем некоторое время и проверяем снова
                    time.sleep(1)
                    idle_count += 1

                    # Если очередь пуста долгое время, завершаем поток
                    if idle_count > 300:  # 5 минут без задач
                        logger.info("Завершение обработчика книг из-за отсутствия задач")
                        break

                    continue

                # Сбрасываем счетчик холостых циклов при наличии задачи
                idle_count = 0

                # Получаем задачу из очереди - это можно делать вне контекста приложения
                book_id, html_content = processing_queue.get(block=False)
                book_size = len(html_content)

                # Проверяем, не была ли уже запущена обработка для этой книги
                if book_id in processing_status and processing_status[book_id].get("status") == "processing":
                    logger.warning(f"Пропуск дублирующейся задачи для книги ID {book_id}")
                    processing_queue.task_done()
                    continue

                # Обновляем статус - это можно делать вне контекста приложения
                processing_status[book_id] = {
                    "status": "processing",
                    "started_at": time.time(),
                    "message": "Book processing has started",
                    "book_size": book_size
                }

                # Запускаем обработку с тайм-аутом
                result = {"status": "timeout", "message": f"Processing timed out after {MAX_PROCESSING_TIME} seconds"}

                def process_with_timeout():
                    nonlocal result
                    try:
                        # process_book_words теперь сам создает контекст приложения
                        result = process_book_words(book_id, html_content)
                    except Exception as proc_err:
                        logger.error(f"Исключение в потоке обработки книги {book_id}: {str(proc_err)}")
                        result = {"status": "error", "message": f"Processing error: {str(proc_err)}"}

                processing_thread = threading.Thread(target=process_with_timeout)
                processing_thread.daemon = True
                processing_thread.start()
                processing_thread.join(MAX_PROCESSING_TIME)

                # Проверяем результат обработки
                if result["status"] == "timeout":
                    logger.warning(f"Обработка книги ID {book_id} превысила тайм-аут {MAX_PROCESSING_TIME} секунд")

                # Обновляем статус с результатом - это можно делать вне контекста приложения
                processing_status[book_id] = {
                    **processing_status.get(book_id, {}),
                    **result,
                    "completed_at": time.time()
                }

                # Помечаем задачу как выполненную
                processing_queue.task_done()

                # Небольшая пауза между задачами для снижения нагрузки
                time.sleep(0.5)

            except queue.Empty:
                # Никаких задач в очереди
                time.sleep(1)
                idle_count += 1
            except Exception as e:
                logger.error(f"Ошибка в обработчике книг: {str(e)}")
                time.sleep(5)  # Небольшая пауза перед следующей попыткой

    finally:
        worker_running = False
        logger.info("Обработчик книг остановлен")

        # Запускаем очистку старых записей при завершении
        cleanup_old_statuses(MAX_STATUS_AGE)


def cleanup_old_statuses(max_age=MAX_STATUS_AGE):
    """
    Очищает старые записи о статусе обработки и планирует следующую очистку

    Args:
        max_age (int): Максимальное время в секундах, после которого запись считается устаревшей
    """
    global cleanup_timer

    try:
        logger.debug("Начало очистки старых записей о статусе обработки книг")
        current_time = time.time()
        to_remove = []

        for book_id, status in processing_status.items():
            # Статусы в процессе обработки не удаляем
            if status.get("status") == "processing":
                # Но проверяем, не зависла ли обработка
                started_at = status.get("started_at", 0)
                if current_time - started_at > MAX_PROCESSING_TIME * 2:
                    logger.warning(f"Обнаружена зависшая обработка книги ID {book_id}, сбрасываем статус")
                    processing_status[book_id] = {
                        **status,
                        "status": "error",
                        "message": "Processing appears to be stuck and was reset",
                        "completed_at": current_time
                    }
                continue

            # Проверяем время завершения или постановки в очередь
            timestamp = status.get("completed_at") or status.get("queued_at", 0)
            if current_time - timestamp > max_age:
                to_remove.append(book_id)

        # Удаляем устаревшие записи
        removed_count = 0
        for book_id in to_remove:
            processing_status.pop(book_id, None)
            removed_count += 1

        if removed_count > 0:
            logger.info(f"Очищено {removed_count} устаревших записей о статусе обработки книг")

    except Exception as e:
        logger.error(f"Ошибка при очистке записей о статусе обработки: {str(e)}")

    finally:
        # Планируем следующую очистку
        if cleanup_timer is not None:
            cleanup_timer = threading.Timer(STATUS_CLEANUP_INTERVAL, cleanup_old_statuses, args=(max_age,))
            cleanup_timer.daemon = True
            cleanup_timer.start()



def populate_block_vocab(book_id: int) -> Dict:
    """
    Заполняет таблицу block_vocab для блоков книги на основе частоты слов.
    
    Args:
        book_id (int): ID книги
        
    Returns:
        Dict: Результат заполнения block_vocab
    """
    try:
        # Получаем все блоки для данной книги
        blocks = Block.query.filter_by(book_id=book_id).all()
        
        if not blocks:
            return {"blocks_updated": 0, "message": "No blocks found for this book"}
        
        blocks_updated = 0
        
        for block in blocks:
            # Очищаем старые записи block_vocab для этого блока
            BlockVocab.query.filter_by(block_id=block.id).delete()
            
            # Получаем главы этого блока
            from app.books.models import BlockChapter, Chapter
            chapter_ids = db.session.query(BlockChapter.chapter_id).filter_by(block_id=block.id).subquery()
            
            # Получаем слова из глав этого блока
            # Используем word_book_link как источник слов для блока
            top_words = db.session.execute(text("""
                SELECT cw.id, cw.english_word, wbl.frequency
                FROM word_book_link wbl
                JOIN collection_words cw ON wbl.word_id = cw.id
                WHERE wbl.book_id = :book_id
                AND LENGTH(cw.english_word) > 3  -- Исключаем короткие слова
                AND cw.english_word NOT IN (
                    'the', 'and', 'that', 'have', 'for', 'not', 'with', 'you', 'this', 'but', 
                    'his', 'from', 'they', 'she', 'her', 'been', 'than', 'has', 'was', 'were'
                )  -- Исключаем стоп-слова
                ORDER BY wbl.frequency DESC
                LIMIT 20  -- 20 слов на блок
            """), {"book_id": book_id}).fetchall()
            
            # Добавляем слова в block_vocab
            words_added = 0
            for word_id, lemma, freq in top_words:
                block_vocab = BlockVocab(
                    block_id=block.id,
                    word_id=word_id,
                    freq=freq
                )
                db.session.add(block_vocab)
                words_added += 1
            
            logger.info(f"Добавлено {words_added} слов в block_vocab для блока {block.block_num}")
            blocks_updated += 1
        
        db.session.commit()
        
        logger.info(f"Обновлено {blocks_updated} блоков с vocabulary для книги ID {book_id}")
        
        return {
            "blocks_updated": blocks_updated,
            "total_blocks": len(blocks)
        }
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при заполнении block_vocab для книги {book_id}: {str(e)}")
        return {"blocks_updated": 0, "error": str(e)}


def process_book_chapters_words(book_id: int) -> Dict:
    """
    Обрабатывает слова из глав книги, создает связи слово-книга и обновляет статистику.
    Эта функция используется для книг, где контент хранится в главах.
    
    Args:
        book_id (int): ID книги
        
    Returns:
        Dict: Статистика об обработанных словах
    """
    try:
        # Проверяем, есть ли уже контекст приложения
        from flask import has_app_context
        
        if has_app_context():
            # Если контекст уже есть, работаем напрямую
            return _process_book_chapters_words_internal(book_id)
        else:
            # Если контекста нет, получаем приложение и создаем контекст
            app = get_app()
            with app.app_context():
                return _process_book_chapters_words_internal(book_id)
                
    except Exception as e:
        logger.error(f"Ошибка при обработке слов из глав книги {book_id}: {str(e)}")
        processing_status[book_id] = {
            "status": "error",
            "message": f"Error processing words: {str(e)}",
            "error_time": time.time()
        }
        return {"status": "error", "message": str(e)}


def _process_book_chapters_words_internal(book_id: int) -> Dict:
    """
    Внутренняя функция обработки слов из глав книги.
    Должна вызываться только внутри контекста приложения.
    
    Args:
        book_id (int): ID книги
        
    Returns:
        Dict: Статистика об обработанных словах
    """
    # Приобретаем семафор для ограничения числа одновременных обработок
    with contextlib.ExitStack() as stack:
        acquired = processing_semaphore.acquire(timeout=5)
        if acquired:
            stack.callback(processing_semaphore.release)
        else:
            logger.warning(
                f"Не удалось получить разрешение для обработки книги ID {book_id} - слишком много одновременных задач")
            return {"status": "error", "message": "Too many concurrent processing tasks"}

        start_time = time.time()
        logger.info(f"Начало обработки слов из глав для книги ID {book_id}")

        # Проверяем существование книги
        try:
            book = Book.query.get(book_id)
            if not book:
                return {"status": "error", "message": f"Book with ID {book_id} not found"}
        except Exception as db_err:
            logger.error(f"Ошибка при проверке существования книги {book_id}: {str(db_err)}")
            return {"status": "error", "message": f"Database error: {str(db_err)}"}

        # Получаем все главы книги
        from app.books.models import Chapter
        chapters = Chapter.query.filter_by(book_id=book_id).all()
        
        if not chapters:
            logger.warning(f"Нет глав для книги ID {book_id}")
            return {"status": "error", "message": "No chapters found"}

        # Объединяем текст всех глав
        all_text = ""
        for chapter in chapters:
            if chapter.text_raw:
                all_text += chapter.text_raw + " "

        if not all_text.strip():
            logger.warning(f"Нет текста в главах книги ID {book_id}")
            return {"status": "error", "message": "No text in chapters"}

        # Извлекаем слова из объединенного текста (обычный текст, не HTML)
        all_words = extract_words_from_text_content(all_text)

        if not all_words:
            logger.warning(f"Не удалось извлечь слова из глав книги ID {book_id}")
            return {"status": "error", "message": "No words extracted"}

        # Получаем статистику
        total_words = len(all_words)
        unique_words = len(set(all_words))

        logger.info(f"Извлечено {total_words} слов, {unique_words} уникальных из глав книги ID {book_id}")

        # Инициализация NLTK ресурсов
        download_nltk_resources()
        _, brown_words, _ = initialize_nltk()

        # Подготовка данных для вставки с обработкой по частям
        batch_size = 5000
        total_added = 0

        for i in range(0, len(all_words), batch_size):
            batch = all_words[i:i + batch_size]
            word_data_batch = prepare_word_data(batch, brown_words)

            # Создание репозитория для работы с БД
            repo = DatabaseRepository()

            # Обрабатываем пакет слов
            batch_added = repo.process_batch_from_original_format(word_data_batch, book_id, batch_size=500)
            total_added += batch_added

            # Обновляем статус
            processed_percent = min(100, int((i + len(batch)) / len(all_words) * 100))
            processing_status[book_id] = {
                **processing_status.get(book_id, {}),
                "status": "processing",
                "progress": processed_percent,
                "message": f"Processing words from chapters: {processed_percent}% complete",
                "words_processed_so_far": total_added
            }

            # Принудительная сборка мусора
            import gc
            gc.collect()

        # Обновляем статистику книги в конце
        repo = DatabaseRepository()
        repo.update_book_stats(book_id, total_words, unique_words)

        # Заполняем block_vocab если есть блоки
        block_vocab_result = populate_block_vocab(book_id)

        elapsed_time = time.time() - start_time
        logger.info(
            f"Завершена обработка {total_added} слов из глав для книги ID {book_id} за {elapsed_time:.2f} секунд")

        return {
            "status": "success",
            "total_words": total_words,
            "unique_words": unique_words,
            "words_added": total_added,
            "block_vocab_populated": block_vocab_result.get("blocks_updated", 0),
            "elapsed_time": elapsed_time
        }


def extract_words_from_text_content(text_content: str) -> List[str]:
    """
    Извлекает слова из обычного текстового контента (не HTML).
    Используется для обработки глав книг.
    
    Args:
        text_content (str): Текстовый контент
        
    Returns:
        List[str]: Список обработанных слов
    """
    try:
        # Загружаем ресурсы NLTK
        download_nltk_resources()
        english_vocab, brown_words, stop_words = initialize_nltk()
        
        # Обрабатываем текст с помощью process_text
        all_words = process_text(text_content, english_vocab, stop_words)
        
        logger.info(f"Извлечено {len(all_words)} слов из текстового контента")
        return all_words
        
    except Exception as e:
        logger.error(f"Ошибка при извлечении слов из текста: {str(e)}")
        return []
