# app/books/processors.py

import logging
import re
import threading
import time
import queue
from typing import Dict, List, Set, Tuple, Optional
import contextlib

from bs4 import BeautifulSoup
from flask import current_app

from app.books.models import Book
from config.settings import (
    MAX_PROCESSING_TIME, MAX_CONCURRENT_PROCESSING,
    STATUS_CLEANUP_INTERVAL, MAX_STATUS_AGE,
    MAX_SYNC_PROCESSING_SIZE, SYNC_PROCESSING_TIMEOUT
)
from app.nlp.setup import download_nltk_resources, initialize_nltk
from app.nlp.processor import prepare_word_data, process_text
from app.words.models import CollectionWords as Word
from app.repository import DatabaseRepository
from app.utils.db import db

logger = logging.getLogger(__name__)

# Очередь для хранения задач обработки книг
processing_queue = queue.Queue()
# Словарь для хранения статуса обработки для каждой книги
processing_status = {}
# Флаг, указывающий, запущен ли обработчик
worker_running = False
# Семафор для ограничения числа одновременных задач
processing_semaphore = threading.Semaphore(MAX_CONCURRENT_PROCESSING)
# Таймер для очистки старых записей
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
        # Импортируем здесь для предотвращения циклических импортов
        from app import create_app
        flask_app = create_app()
    return flask_app


def extract_words_from_html_content(html_content: str) -> List[str]:
    """
    Извлекает слова из HTML-контента книги.

    Args:
        html_content (str): HTML-контент книги

    Returns:
        List[str]: Список обработанных слов
    """
    try:
        # Загружаем ресурсы NLTK
        download_nltk_resources()
        english_vocab, brown_words, stop_words = initialize_nltk()

        # Удаляем HTML-теги
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text()

        # Проверяем, что текст не пустой
        if not text or len(text.strip()) < 10:
            logger.warning("HTML-контент не содержит текста или слишком короткий для обработки")
            return []

        # Обрабатываем текст
        words = process_text(text, english_vocab, stop_words)

        return words
    except Exception as e:
        logger.error(f"Ошибка при извлечении слов из HTML-контента: {str(e)}")
        return []


def process_book_words(book_id: int, html_content: str) -> Dict:
    """
    Обрабатывает слова из книги, создает связи слово-книга и обновляет статистику.
    Использует пакетную обработку для оптимизации производительности.

    Args:
        book_id (int): ID книги
        html_content (str): HTML-контент книги

    Returns:
        Dict: Статистика об обработанных словах
    """
    # Получаем приложение
    app = get_app()

    try:
        # Запускаем обработку в контексте приложения
        with app.app_context():
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

                # Извлекаем слова из контента
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

                # Подготовка данных для вставки
                word_data = prepare_word_data(all_words, brown_words)

                # Создание репозитория для работы с БД
                repo = DatabaseRepository()

                # Обновляем статистику книги
                repo.update_book_stats(book_id, total_words, unique_words)

                # Используем метод пакетной обработки из репозитория
                # Этот метод оптимизирован для больших объемов данных
                words_added = repo.process_batch_from_original_format(word_data, book_id, batch_size=500)

                elapsed_time = time.time() - start_time
                logger.info(
                    f"Завершена обработка {words_added} слов для книги ID {book_id} за {elapsed_time:.2f} секунд")

                return {
                    "status": "success",
                    "total_words": total_words,
                    "unique_words": unique_words,
                    "words_added": words_added,
                    "elapsed_time": elapsed_time
                }

    except Exception as e:
        logger.error(f"Ошибка при обработке слов для книги ID {book_id}: {str(e)}")
        return {"status": "error", "message": str(e)}


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
