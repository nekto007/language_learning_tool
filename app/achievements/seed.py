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
]


def seed_achievements():
    """
    Seed initial achievements data
    Safe to call multiple times - only inserts missing achievements
    """
    # Check if already seeded
    if Achievement.query.count() > 0:
        return

    # Add all achievements
    for achievement_data in INITIAL_ACHIEVEMENTS:
        achievement = Achievement(**achievement_data)
        db.session.add(achievement)

    db.session.commit()