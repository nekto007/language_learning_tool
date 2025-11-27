# Архитектура книжных курсов (Book Courses)

## Обзор

Книжные курсы — это система обучения английскому через чтение книг. Книга разбивается на модули (блоки глав), каждый модуль — на ежедневные уроки (~800 слов текста + словарь + задания).

```
Book → BookCourse → Modules → DailyLessons → SliceVocabulary
                      ↓
              Enrollment → Progress → Completion
```

---

## 1. Модели данных

### 1.1 Книги и блоки

**Файл:** `app/books/models.py`

| Модель | Назначение |
|--------|------------|
| `Book` | Информация о книге (title, author, level, chapters_cnt) |
| `Chapter` | Главы книги (text_raw, words, audio_url) |
| `Block` | Экзаменационный блок из 2-3 глав (grammar_key, focus_vocab) |
| `BlockVocab` | Словарь блока (word_id, freq) |
| `Task` | Задания для блока (task_type: reading_mcq, match_headings, etc.) |

### 1.2 Курсы

**Файл:** `app/curriculum/book_courses.py`

| Модель | Назначение |
|--------|------------|
| `BookCourse` | Курс на основе книги |
| `BookCourseModule` | Модуль курса (= Block) |
| `BookCourseEnrollment` | Запись студента на курс |
| `BookModuleProgress` | Прогресс в модуле |

### 1.3 Ежедневные уроки

**Файл:** `app/curriculum/daily_lessons.py`

| Модель | Назначение |
|--------|------------|
| `DailyLesson` | Дневной урок (~800 слов текста) |
| `SliceVocabulary` | Словарь для урока (10 слов с контекстом) |
| `UserLessonProgress` | Прогресс студента в уроке |

---

## 2. Процесс создания курса (Admin)

### 2.1 Маршруты админки

**Файл:** `app/admin/book_courses.py`

```
GET  /admin/book-courses                    → Список курсов
GET  /admin/book-courses/create             → Форма создания
POST /admin/book-courses/create             → Создание курса
POST /admin/book-courses/<id>/generate-modules → Генерация модулей
```

### 2.2 Процесс генерации

```
1. Админ создает курс из книги
       ↓
2. BookCourseGenerator запускается
       ↓
3. Создается BookCourse запись
       ↓
4. BlockSchemaImporter создает Block записи (группы глав)
       ↓
5. VocabularyExtractor извлекает словарь для блоков
       ↓
6. TaskGenerators создают задания (MCQ, cloze, etc.)
       ↓
7. Создаются BookCourseModule из Block
       ↓
8. DailySliceGenerator нарезает текст на уроки (~800 слов)
       ↓
9. Для каждого урока создается SliceVocabulary (10 слов)
```

### 2.3 Ключевые сервисы

**Файл:** `app/curriculum/services/`

| Сервис | Назначение |
|--------|------------|
| `BookCourseGenerator` | Основной оркестратор создания курса |
| `BlockSchemaImporter` | Импорт/генерация структуры блоков |
| `DailySliceGenerator` | Нарезка текста на уроки |
| `VocabularyExtractor` | Извлечение словаря |

### 2.4 Пример кода создания

```python
from app.curriculum.services.book_course_generator import BookCourseGenerator

generator = BookCourseGenerator(book_id=5)
course = generator.create_course_from_book(
    course_title="Learn English with Harry Potter",
    course_description="...",
    level="B1"
)
# Создает: BookCourse + Modules + DailyLessons + Vocabulary
```

---

## 3. Процесс обучения (Student)

### 3.1 Маршруты студента

**Файл:** `app/curriculum/routes/book_courses.py`

```
GET  /curriculum/book-courses                    → Список курсов
GET  /curriculum/book-courses/<id>               → Детали курса
POST /curriculum/book-courses/<id>/enroll        → Записаться
GET  /curriculum/book-courses/<id>/modules/<id>  → Просмотр модуля
GET  /curriculum/book-courses/<id>/modules/<id>/lesson/<id> → Урок
```

### 3.2 Поток обучения

```
1. ВЫБОР КУРСА
   Студент видит список курсов → выбирает → нажимает "Записаться"
       ↓
2. ЗАПИСЬ (BookCourseEnrollment)
   Создается enrollment, current_module = первый модуль
       ↓
3. ПРОСМОТР МОДУЛЕЙ
   Студент видит список модулей, заблокированные модули недоступны
       ↓
4. ОТКРЫТИЕ МОДУЛЯ
   Создается BookModuleProgress, загружаются DailyLessons
       ↓
5. ПРОХОЖДЕНИЕ УРОКОВ
   День 1: Vocabulary (изучение 10 слов)
   День 1: Reading (чтение текста + задание)
   День 2: ...
       ↓
6. ЗАВЕРШЕНИЕ МОДУЛЯ
   Все уроки пройдены → модуль завершен → следующий разблокирован
```

### 3.3 Типы уроков

| Тип | Описание | Шаблон |
|-----|----------|--------|
| `vocabulary` | Изучение 10 слов (flashcards) | `vocabulary.html` |
| `reading_passage` | Чтение текста | `reading_passage.html` |
| `reading_mcq` | Тест множественного выбора | `reading_mcq.html` |
| `match_headings` | Соответствие заголовков | `match_headings.html` |
| `open_cloze` | Заполнение пропусков | `open_cloze.html` |
| `word_formation` | Словообразование | `word_formation.html` |
| `grammar_sheet` | Грамматика | `grammar.html` |
| `final_test` | Финальный тест | `final_test.html` |

---

## 4. Структура файлов

```
app/
├── books/
│   └── models.py              # Book, Chapter, Block, Task
│
├── curriculum/
│   ├── book_courses.py        # BookCourse, Module, Enrollment, Progress
│   ├── daily_lessons.py       # DailyLesson, SliceVocabulary
│   ├── routes/
│   │   └── book_courses.py    # Student routes
│   └── services/
│       ├── book_course_generator.py    # Основной генератор
│       ├── block_schema_importer.py    # Импорт блоков
│       ├── daily_slice_generator.py    # Нарезка на уроки
│       └── vocabulary_extractor.py     # Извлечение словаря
│
├── admin/
│   └── book_courses.py        # Admin routes
│
└── templates/
    └── curriculum/book_courses/
        ├── list.html          # Список курсов
        ├── course_detail.html # Детали курса
        ├── module_detail.html # Модуль с уроками
        └── lessons/
            ├── _lesson_base.html
            ├── vocabulary.html
            ├── reading_passage.html
            └── ...
```

---

## 5. Связи между моделями

```
Book (1) ──────────────────────────────── (N) Chapter
  │                                             │
  └─── (1) BookCourse                          │
            │                                   │
            ├─── (N) BookCourseModule ─── (1) Block ─── (N) BlockChapter
            │            │
            │            └─── (N) DailyLesson
            │                      │
            │                      ├─── (N) SliceVocabulary ─── CollectionWords
            │                      │
            │                      └─── (N) UserLessonProgress
            │
            └─── (N) BookCourseEnrollment ─── User
                          │
                          └─── (N) BookModuleProgress
```

---

## 6. Константы и настройки

```python
# daily_slice_generator.py
SLICE_SIZE = 800       # Слов в уроке
SLICE_TOLERANCE = 50   # Допустимое отклонение (+/- 50 слов)

# Ротация типов заданий
LESSON_TYPES_ROTATION = [
    'reading_mcq',
    'match_headings',
    'open_cloze',
    'word_formation',
    'keyword_transform',
    'grammar_sheet'
]

# vocabulary_extractor.py
MAX_WORDS_PER_BLOCK = 20   # Слов в словаре блока
MAX_WORDS_PER_SLICE = 10   # Слов в уроке
```

---

## 7. API эндпоинты

### Student API

```
GET  /curriculum/api/v1/lesson/<id>           → Данные урока
POST /curriculum/api/v1/lesson/<id>/complete  → Завершить урок
GET  /curriculum/api/v1/lesson/<id>/vocabulary → Словарь урока
```

### Progress Tracking

```python
# После завершения урока
UserLessonProgress.status = 'completed'
UserLessonProgress.score = 85
UserLessonProgress.completed_at = datetime.now()

# Пересчет прогресса модуля
completed = len([l for l in lessons if l.status == 'completed'])
BookModuleProgress.progress_percentage = completed / total * 100
```

---

## 8. Пример: полный цикл

### Админ создает курс

```python
# 1. Генерация курса
generator = BookCourseGenerator(book_id=1)
course = generator.create_course_from_book(
    course_title="Harry Potter Course",
    course_description="Learn English with Harry Potter",
    level="B1"
)

# Результат:
# - BookCourse (id=1)
# - 5 BookCourseModule (chapters 1-3, 4-6, ...)
# - 30 DailyLesson (по 6 дней на модуль)
# - 300 SliceVocabulary (по 10 слов на урок)
```

### Студент проходит курс

```python
# 1. Запись
enrollment = BookCourseEnrollment(user_id=5, course_id=1)

# 2. Открытие модуля
progress = BookModuleProgress(enrollment_id=1, module_id=1)

# 3. Прохождение урока
daily_lesson = DailyLesson.query.get(301)
# lesson_type = 'vocabulary'
# -> показывается vocabulary.html с 10 словами

# 4. Завершение
UserLessonProgress(
    user_id=5,
    daily_lesson_id=301,
    status='completed',
    score=100
)
```

---

## 9. Диаграмма потока данных

```
┌─────────────────────────────────────────────────────────────┐
│                     ADMIN INTERFACE                          │
│                                                              │
│  Book → [Create Course] → BookCourseGenerator               │
│                              ↓                               │
│         BlockSchemaImporter → Blocks                        │
│         VocabularyExtractor → BlockVocab                    │
│         DailySliceGenerator → DailyLessons + SliceVocab     │
└─────────────────────────────────────────────────────────────┘
                              ↓
                         [DATABASE]
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    STUDENT INTERFACE                         │
│                                                              │
│  [List Courses] → BookCourse.query.filter(is_active=True)   │
│        ↓                                                     │
│  [Enroll] → BookCourseEnrollment.create()                   │
│        ↓                                                     │
│  [View Module] → DailyLesson.query.filter(module_id=X)      │
│        ↓                                                     │
│  [Take Lesson] → vocabulary.html / reading_passage.html     │
│        ↓                                                     │
│  [Complete] → UserLessonProgress.update(status='completed') │
└─────────────────────────────────────────────────────────────┘
```
