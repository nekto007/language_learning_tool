#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор аудиофайлов для reading-уроков книжных курсов
Читает данные из БД (DailyLesson), генерирует аудио через edge-tts/gTTS,
сохраняет файлы и обновляет audio_url в БД.
"""

import asyncio
import os
import re
import shutil
from pathlib import Path

from app import create_app, db
from app.curriculum.book_courses import BookCourse, BookCourseModule
from app.curriculum.daily_lessons import DailyLesson


class BookAudioGenerator:
    def __init__(self, method: str = 'edge-tts', voice_type: str = 'female'):
        """
        method: 'gtts', 'edge-tts'
        voice_type: 'male', 'female'
        """
        self.method = method
        self.voice_type = voice_type
        self.base_dir = Path(__file__).resolve().parent
        self.audio_dir = self.base_dir / 'app/static/audio/lessons'
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        # Счётчики
        self.total_processed = 0
        self.successful = 0
        self.skipped = 0
        self.failed = 0

        # Настройка голосов для edge-tts
        self.edge_voices = {
            'female': {
                'us': 'en-US-AriaNeural',
                'uk': 'en-GB-SoniaNeural',
            },
            'male': {
                'us': 'en-US-GuyNeural',
                'uk': 'en-GB-RyanNeural',
            }
        }

        # Режим перезаписи: None = спрашивать, True = перезаписывать, False = пропускать
        self.overwrite_mode: bool | None = None

    def _clean_text_for_audio(self, text: str) -> str:
        """Очистка текста для лучшего произношения"""
        # Удаляем ссылки на аудиофайлы
        text = re.sub(r'audio.*?\.mp3', '', text)
        text = re.sub(r'\n\n+', '. ', text)

        replacements = {
            'e.g.': 'for example',
            'i.e.': 'that is',
            'etc.': 'and so on',
            'vs.': 'versus',
            '&': 'and',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        return text.strip()

    def _should_overwrite_file(self, filepath: Path) -> bool:
        """Проверка, нужно ли перезаписывать файл"""
        if not filepath.exists():
            return True

        if self.overwrite_mode is True:
            return True
        elif self.overwrite_mode is False:
            return False

        print(f"\n⚠️  Файл {filepath.name} уже существует!")
        print("1. Перезаписать этот файл")
        print("2. Пропустить этот файл")
        print("3. Перезаписать ВСЕ существующие файлы")
        print("4. Пропустить ВСЕ существующие файлы")

        while True:
            try:
                choice = input("Ваш выбор (1-4): ").strip()
                if choice == '1':
                    return True
                elif choice == '2':
                    return False
                elif choice == '3':
                    self.overwrite_mode = True
                    return True
                elif choice == '4':
                    self.overwrite_mode = False
                    return False
                else:
                    print("Введите число от 1 до 4.")
            except KeyboardInterrupt:
                print("\n\nОтменено пользователем")
                return False

    async def _create_audio_edge(self, text: str, filepath: Path, accent: str = 'us') -> bool:
        """Создание аудио через edge-tts"""
        try:
            import edge_tts

            voice_type = self.voice_type if self.voice_type in self.edge_voices else 'female'
            voice = self.edge_voices[voice_type][accent]

            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(filepath))
            return True

        except Exception as e:
            print(f"❌ Edge-TTS ошибка: {e}")
            return False

    def _create_audio_gtts(self, text: str, filepath: Path, accent: str = 'us') -> bool:
        """Создание аудио через gTTS"""
        try:
            from gtts import gTTS

            tld_map = {'us': 'com', 'uk': 'co.uk', 'au': 'com.au'}
            tld = tld_map.get(accent, 'com')

            tts = gTTS(text=text, lang='en', tld=tld, slow=False)
            tts.save(str(filepath))
            return True

        except Exception as e:
            print(f"❌ gTTS ошибка: {e}")
            return False

    async def create_audio(self, text: str, filepath: Path, accent: str = 'us') -> bool:
        """Создание аудиофайла выбранным методом"""
        clean_text = self._clean_text_for_audio(text)

        if not clean_text:
            print("   ⚠️  Пустой текст после очистки, пропуск")
            return False

        # Разбиваем длинный текст на части (edge-tts лимит ~5000 символов)
        if len(clean_text) > 4500:
            return await self._create_long_audio(clean_text, filepath, accent)

        if self.method == 'gtts':
            return self._create_audio_gtts(clean_text, filepath, accent)
        elif self.method == 'edge-tts':
            return await self._create_audio_edge(clean_text, filepath, accent)
        else:
            print(f"❌ Неизвестный метод: {self.method}")
            return False

    async def _create_long_audio(self, text: str, filepath: Path, accent: str = 'us') -> bool:
        """Генерация аудио для длинного текста: разбивает на части и склеивает"""
        # Разбиваем по предложениям
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks: list[str] = []
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > 4500:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk += " " + sentence if current_chunk else sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        if len(chunks) == 1:
            # Уместилось в один чанк
            if self.method == 'gtts':
                return self._create_audio_gtts(chunks[0], filepath, accent)
            else:
                return await self._create_audio_edge(chunks[0], filepath, accent)

        # Генерируем каждый чанк
        temp_dir = self.base_dir / 'temp_book_audio'
        temp_dir.mkdir(parents=True, exist_ok=True)

        part_files: list[Path] = []
        for i, chunk in enumerate(chunks):
            part_path = temp_dir / f"part_{i}.mp3"
            if self.method == 'gtts':
                success = self._create_audio_gtts(chunk, part_path, accent)
            else:
                success = await self._create_audio_edge(chunk, part_path, accent)

            if not success:
                # Чистим временные файлы
                for pf in part_files:
                    pf.unlink(missing_ok=True)
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False
            part_files.append(part_path)

        # Склеиваем через ffmpeg
        success = self._merge_audio_files(part_files, filepath, temp_dir)

        # Чистим
        shutil.rmtree(temp_dir, ignore_errors=True)
        return success

    def _merge_audio_files(self, parts: list[Path], output: Path, temp_dir: Path) -> bool:
        """Объединение аудиофайлов через ffmpeg"""
        try:
            list_file = temp_dir / "concat_list.txt"
            with open(list_file, 'w') as f:
                for part in parts:
                    f.write(f"file '{part.absolute()}'\n")

            cmd = f'ffmpeg -f concat -safe 0 -i "{list_file}" -c:a libmp3lame -b:a 128k "{output}" -y -loglevel warning'
            result = os.system(cmd)
            return result == 0

        except Exception as e:
            print(f"❌ Ошибка объединения: {e}")
            return False

    def _make_audio_filename(self, course: BookCourse, module: BookCourseModule, lesson: DailyLesson) -> str:
        """Генерация имени файла: course_{id}_ch{module}_lesson{day}.mp3"""
        return f"course_{course.id}_ch{module.module_number}_lesson{lesson.day_number}.mp3"

    async def process_course(self, course_id: int, accent: str = 'us') -> None:
        """Обработка книжного курса: генерация аудио для reading-уроков без audio_url"""

        course = BookCourse.query.get(course_id)
        if not course:
            print(f"❌ Курс с ID {course_id} не найден")
            return

        print(f"\n{'='*60}")
        print(f"📚 Курс: {course.title} ({course.level})")
        print(f"{'='*60}")

        modules = (BookCourseModule.query
                   .filter_by(course_id=course.id)
                   .order_by(BookCourseModule.module_number)
                   .all())

        if not modules:
            print("   ⚠️  Нет модулей")
            return

        for module in modules:
            # Получаем ВСЕ reading-уроки, проверяем файл на диске
            all_reading = (DailyLesson.query
                           .filter_by(book_course_module_id=module.id, lesson_type='reading')
                           .order_by(DailyLesson.day_number)
                           .all())

            # Фильтруем: нет audio_url ИЛИ файл физически отсутствует
            lessons = []
            for l in all_reading:
                filename = self._make_audio_filename(course, module, l)
                filepath = self.audio_dir / filename
                if not l.audio_url or not filepath.exists():
                    lessons.append(l)

            if not lessons:
                continue

            print(f"\n📖 Модуль {module.module_number}: {module.title}")
            print(f"   📝 Без аудио: {len(lessons)} reading-уроков (из {len(all_reading)})")

            for lesson in lessons:
                self.total_processed += 1

                if not lesson.slice_text:
                    print(f"   ⚠️  День {lesson.day_number}: пустой текст, пропуск")
                    self.skipped += 1
                    continue

                filename = self._make_audio_filename(course, module, lesson)
                filepath = self.audio_dir / filename
                audio_url = f"audio/lessons/{filename}"

                word_count = lesson.word_count or len(lesson.slice_text.split())
                print(f"   🎙️  День {lesson.day_number}: {word_count} слов → {filename}")

                # Проверяем, нужно ли создавать файл
                if not self._should_overwrite_file(filepath):
                    print(f"      ⏭️  Пропущен (файл существует)")
                    self.skipped += 1

                    # Файл есть, но audio_url нет — обновляем
                    lesson.audio_url = audio_url
                    db.session.commit()
                    print(f"      📝 audio_url обновлён в БД")
                    continue

                # Генерируем аудио
                print(f"      🔄 Генерирую...")
                success = await self.create_audio(lesson.slice_text, filepath, accent)

                if success:
                    self.successful += 1
                    print(f"      ✅ Готово ({filepath.stat().st_size // 1024} KB)")

                    lesson.audio_url = audio_url
                    db.session.commit()
                    print(f"      📝 audio_url = {audio_url}")
                else:
                    self.failed += 1
                    print(f"      ❌ Ошибка генерации")

        # Итоги
        print(f"\n{'='*60}")
        print(f"🎉 ЗАВЕРШЕНО!")
        print(f"📊 Обработано: {self.total_processed}")
        print(f"✅ Успешно: {self.successful}")
        print(f"⏭️  Пропущено: {self.skipped}")
        print(f"❌ Ошибок: {self.failed}")
        print(f"📁 Аудио: {self.audio_dir}")
        print(f"{'='*60}")


def show_courses_and_ask() -> int:
    """Показать список курсов и запросить ID у пользователя"""
    courses = BookCourse.query.filter_by(is_active=True).all()

    if not courses:
        print("❌ Нет активных книжных курсов в БД")
        raise SystemExit(1)

    print("\nДоступные книжные курсы:")
    print("-" * 60)
    for c in courses:
        # Считаем reading-уроки без аудио
        reading_total = (DailyLesson.query
                         .join(BookCourseModule)
                         .filter(BookCourseModule.course_id == c.id,
                                 DailyLesson.lesson_type == 'reading')
                         .count())
        # Считаем уроки без файла на диске
        audio_dir = Path(__file__).resolve().parent / 'app/static/audio/lessons'
        reading_no_audio_rows = (db.session.query(DailyLesson, BookCourseModule.module_number)
                                 .join(BookCourseModule)
                                 .filter(BookCourseModule.course_id == c.id,
                                         DailyLesson.lesson_type == 'reading')
                                 .all())
        reading_no_audio = sum(
            1 for l, mod_num in reading_no_audio_rows
            if not l.audio_url
            or not (audio_dir / f"course_{c.id}_ch{mod_num}_lesson{l.day_number}.mp3").exists()
        )
        print(f"  [{c.id}] {c.title} ({c.level}) — "
              f"reading: {reading_total}, без аудио: {reading_no_audio}")
    print("-" * 60)

    while True:
        try:
            raw = input("\nВведите ID курса: ").strip()
            course_id = int(raw)
            if any(c.id == course_id for c in courses):
                return course_id
            print(f"Курс с ID {course_id} не найден. Попробуйте ещё раз.")
        except ValueError:
            print("Введите число.")
        except KeyboardInterrupt:
            print("\n\nОтменено.")
            raise SystemExit(0)


async def main():
    print("🎵 Генератор аудио для reading-уроков книжных курсов")
    print("=" * 60)

    # Запрашиваем курс у пользователя
    course_id = show_courses_and_ask()

    # ===== НАСТРОЙКИ =====
    METHOD = 'edge-tts'       # 'gtts' или 'edge-tts'
    VOICE_TYPE = 'female'     # 'male' или 'female'
    ACCENT = 'us'             # 'us' или 'uk'
    AUTO_OVERWRITE = None     # None = спрашивать, True = перезаписать, False = пропустить
    # =====================

    generator = BookAudioGenerator(method=METHOD, voice_type=VOICE_TYPE)
    generator.overwrite_mode = AUTO_OVERWRITE

    await generator.process_course(
        course_id=course_id,
        accent=ACCENT,
    )


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        asyncio.run(main())
