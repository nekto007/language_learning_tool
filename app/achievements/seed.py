"""
Seed initial achievements data
"""
from app.utils.db import db
from app.study.models import Achievement


INITIAL_ACHIEVEMENTS = [
    # First steps
    {
        'code': 'first_lesson',
        'name': 'Первый урок',
        'description': 'Завершите первый урок',
        'icon': '🎯',
        'xp_reward': 10,
        'category': 'lessons'
    },

    # Lesson achievements
    {
        'code': 'lessons_5',
        'name': 'Начинающий',
        'description': 'Завершите 5 уроков',
        'icon': '📚',
        'xp_reward': 50,
        'category': 'lessons'
    },
    {
        'code': 'lessons_10',
        'name': 'Ученик',
        'description': 'Завершите 10 уроков',
        'icon': '🎓',
        'xp_reward': 150,
        'category': 'lessons'
    },
    {
        'code': 'lessons_25',
        'name': 'Знаток',
        'description': 'Завершите 25 уроков',
        'icon': '🏆',
        'xp_reward': 300,
        'category': 'lessons'
    },
    {
        'code': 'lessons_50',
        'name': 'Отличник',
        'description': 'Завершите 50 уроков',
        'icon': '📜',
        'xp_reward': 500,
        'category': 'lessons'
    },
    {
        'code': 'lessons_100',
        'name': 'Магистр',
        'description': 'Завершите 100 уроков',
        'icon': '👑',
        'xp_reward': 1000,
        'category': 'lessons'
    },

    # Perfect scores
    {
        'code': 'perfect_score',
        'name': 'Перфекционист',
        'description': 'Получите 100% в любом уроке',
        'icon': '💯',
        'xp_reward': 50,
        'category': 'score'
    },
    {
        'code': 'perfect_quiz',
        'name': 'Идеальный квиз',
        'description': 'Пройдите квиз без ошибок',
        'icon': '✨',
        'xp_reward': 75,
        'category': 'quiz'
    },

    # Streaks
    {
        'code': 'daily_streak_3',
        'name': 'Постоянство',
        'description': 'Занимайтесь 3 дня подряд',
        'icon': '🔥',
        'xp_reward': 30,
        'category': 'streak'
    },
    {
        'code': 'daily_streak_7',
        'name': 'Недельная серия',
        'description': 'Занимайтесь 7 дней подряд',
        'icon': '📅',
        'xp_reward': 100,
        'category': 'streak'
    },
    {
        'code': 'daily_streak_14',
        'name': 'Две недели подряд',
        'description': 'Занимайтесь 14 дней подряд',
        'icon': '📆',
        'xp_reward': 300,
        'category': 'streak'
    },
    {
        'code': 'daily_streak_30',
        'name': 'Месячная серия',
        'description': 'Занимайтесь 30 дней подряд',
        'icon': '🗓️',
        'xp_reward': 600,
        'category': 'streak'
    },

    # Books
    {
        'code': 'first_book',
        'name': 'Первая книга',
        'description': 'Прочитайте первую книгу до конца',
        'icon': '📖',
        'xp_reward': 100,
        'category': 'books'
    },
    {
        'code': 'books_5',
        'name': 'Книголюб',
        'description': 'Прочитайте 5 книг',
        'icon': '📚',
        'xp_reward': 300,
        'category': 'books'
    },
    {
        'code': 'books_10',
        'name': 'Библиофил',
        'description': 'Прочитайте 10 книг',
        'icon': '📕',
        'xp_reward': 600,
        'category': 'books'
    },

    # Flashcards
    {
        'code': 'cards_100',
        'name': 'Карточный новичок',
        'description': 'Повторите 100 карточек',
        'icon': '🎴',
        'xp_reward': 100,
        'category': 'flashcards'
    },
    {
        'code': 'cards_500',
        'name': 'Карточный мастер',
        'description': 'Повторите 500 карточек',
        'icon': '🃏',
        'xp_reward': 300,
        'category': 'flashcards'
    },
    {
        'code': 'perfect_session',
        'name': 'Идеальная сессия',
        'description': 'Завершите сессию карточек с 100% правильных ответов',
        'icon': '💯',
        'xp_reward': 75,
        'category': 'flashcards'
    },

    # Levels
    {
        'code': 'level_10',
        'name': 'Десятка',
        'description': 'Достигните 10 уровня',
        'icon': '🔟',
        'xp_reward': 100,
        'category': 'levels'
    },
    {
        'code': 'level_25',
        'name': 'Четверть сотни',
        'description': 'Достигните 25 уровня',
        'icon': '🎯',
        'xp_reward': 250,
        'category': 'levels'
    },
    {
        'code': 'level_50',
        'name': 'Полусотня',
        'description': 'Достигните 50 уровня',
        'icon': '🌟',
        'xp_reward': 500,
        'category': 'levels'
    },

    # Quiz achievements
    {
        'code': 'first_quiz',
        'name': 'Первый квиз',
        'description': 'Завершите свой первый квиз',
        'icon': '🎯',
        'xp_reward': 50,
        'category': 'quiz'
    },
    {
        'code': 'quiz_master_10',
        'name': 'Мастер квизов',
        'description': 'Завершите 10 квизов',
        'icon': '🏆',
        'xp_reward': 150,
        'category': 'quiz'
    },
    {
        'code': 'quiz_master_50',
        'name': 'Гуру квизов',
        'description': 'Завершите 50 квизов',
        'icon': '👑',
        'xp_reward': 500,
        'category': 'quiz'
    },
    {
        'code': 'quiz_streak_5',
        'name': 'Серия из 5',
        'description': 'Ответьте правильно на 5 вопросов подряд',
        'icon': '🔥',
        'xp_reward': 50,
        'category': 'quiz'
    },
    {
        'code': 'high_score_90',
        'name': 'Отличник',
        'description': 'Получите 90%+ в квизе из 10+ вопросов',
        'icon': '⭐',
        'xp_reward': 50,
        'category': 'quiz'
    },
    {
        'code': 'speed_demon',
        'name': 'Спидран',
        'description': 'Завершите квиз из 10+ вопросов за 2 минуты',
        'icon': '⚡',
        'xp_reward': 75,
        'category': 'quiz'
    },

    # More flashcards
    {
        'code': 'cards_1000',
        'name': 'Карточный гуру',
        'description': 'Повторите 1000 карточек',
        'icon': '👑',
        'xp_reward': 600,
        'category': 'flashcards'
    },

    # More books
    {
        'code': 'chapter_marathon',
        'name': 'Марафон глав',
        'description': 'Прочитайте 50 глав',
        'icon': '🏃',
        'xp_reward': 250,
        'category': 'books'
    },

    # More streaks
    {
        'code': 'daily_streak_60',
        'name': 'Два месяца подряд',
        'description': 'Занимайтесь 60 дней подряд',
        'icon': '📊',
        'xp_reward': 1000,
        'category': 'streak'
    },
    {
        'code': 'daily_streak_100',
        'name': 'Сто дней подряд',
        'description': 'Занимайтесь 100 дней подряд',
        'icon': '💪',
        'xp_reward': 2000,
        'category': 'streak'
    },

    # Words/Study
    {
        'code': 'words_learned_100',
        'name': 'Полиглот',
        'description': 'Изучите 100 слов',
        'icon': '📚',
        'xp_reward': 200,
        'category': 'study'
    },
    {
        'code': 'words_learned_500',
        'name': 'Мастер слов',
        'description': 'Изучите 500 слов',
        'icon': '🎓',
        'xp_reward': 1000,
        'category': 'study'
    },

    # Matching game
    {
        'code': 'matching_first',
        'name': 'Первое совпадение',
        'description': 'Завершите первую игру на совпадение',
        'icon': '🎯',
        'xp_reward': 25,
        'category': 'matching'
    },
    {
        'code': 'matching_perfect',
        'name': 'Идеальное совпадение',
        'description': 'Завершите игру со 100% точностью',
        'icon': '🎊',
        'xp_reward': 50,
        'category': 'matching'
    },
    {
        'code': 'matching_speed',
        'name': 'Скоростное совпадение',
        'description': 'Завершите игру быстрее чем за 1 минуту',
        'icon': '⚡',
        'xp_reward': 40,
        'category': 'matching'
    },

    # Special time-based
    {
        'code': 'early_bird',
        'name': 'Ранняя пташка',
        'description': 'Завершите квиз до 8:00 утра',
        'icon': '🌅',
        'xp_reward': 25,
        'category': 'special'
    },
    {
        'code': 'night_owl',
        'name': 'Сова',
        'description': 'Завершите квиз после 23:00',
        'icon': '🦉',
        'xp_reward': 25,
        'category': 'special'
    },

    # Daily plan mission badges
    {
        'code': 'mission_first',
        'name': 'Первая миссия',
        'description': 'Завершите первую ежедневную миссию',
        'icon': '🚀',
        'xp_reward': 25,
        'category': 'mission'
    },
    {
        'code': 'mission_progress_5',
        'name': 'Исследователь',
        'description': 'Завершите 5 миссий прогресса',
        'icon': '🧭',
        'xp_reward': 100,
        'category': 'mission'
    },
    {
        'code': 'mission_repair_5',
        'name': 'Мастер ремонта',
        'description': 'Завершите 5 миссий восстановления',
        'icon': '🔧',
        'xp_reward': 100,
        'category': 'mission'
    },
    {
        'code': 'mission_reading_5',
        'name': 'Читатель',
        'description': 'Завершите 5 миссий чтения',
        'icon': '📖',
        'xp_reward': 100,
        'category': 'mission'
    },
    {
        'code': 'mission_week_perfect',
        'name': 'Идеальная неделя',
        'description': 'Завершите миссии 7 дней подряд',
        'icon': '🌟',
        'xp_reward': 300,
        'category': 'mission'
    },
    {
        'code': 'mission_early_bird',
        'name': 'Утренняя миссия',
        'description': 'Завершите ежедневную миссию до 9:00 утра',
        'icon': '🌄',
        'xp_reward': 50,
        'category': 'mission'
    },
    {
        'code': 'mission_night_owl',
        'name': 'Ночная миссия',
        'description': 'Завершите ежедневную миссию после 22:00',
        'icon': '🌙',
        'xp_reward': 50,
        'category': 'mission'
    },
    {
        'code': 'mission_variety_3',
        'name': 'Разносторонний',
        'description': 'За неделю завершите все 3 типа миссий',
        'icon': '🎭',
        'xp_reward': 150,
        'category': 'mission'
    },
    {
        'code': 'mission_speed_demon',
        'name': 'Молниеносный',
        'description': 'Завершите все этапы миссии менее чем за 30 минут',
        'icon': '⚡',
        'xp_reward': 100,
        'category': 'mission'
    },
]


def seed_achievements():
    """
    Seed initial achievements data.

    Idempotent: inserts only achievements whose code is missing from the
    database, so calling repeatedly after adding new badge definitions will
    add only the new ones.
    """
    existing_codes = {code for (code,) in db.session.query(Achievement.code).all()}

    added = 0
    for achievement_data in INITIAL_ACHIEVEMENTS:
        if achievement_data['code'] in existing_codes:
            continue
        db.session.add(Achievement(**achievement_data))
        added += 1

    if added:
        db.session.commit()