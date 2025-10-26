"""
Add new achievements to the system
"""
from app import create_app
from app.utils.db import db
from app.study.models import Achievement

NEW_ACHIEVEMENTS = [
    # Book reading achievements
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
    {
        'code': 'chapter_marathon',
        'name': 'Марафон глав',
        'description': 'Прочитайте 50 глав',
        'icon': '🏃',
        'xp_reward': 250,
        'category': 'books'
    },

    # Flashcard achievements
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
        'code': 'cards_1000',
        'name': 'Карточный гуру',
        'description': 'Повторите 1000 карточек',
        'icon': '👑',
        'xp_reward': 600,
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

    # Matching game achievements
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

    # Lesson achievements
    {
        'code': 'lessons_10',
        'name': 'Ученик',
        'description': 'Завершите 10 уроков',
        'icon': '🎓',
        'xp_reward': 150,
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
        'icon': '🏆',
        'xp_reward': 1000,
        'category': 'lessons'
    },

    # Streak achievements (extending existing)
    {
        'code': 'daily_streak_14',
        'name': 'Две недели подряд',
        'description': 'Занимайтесь 14 дней подряд',
        'icon': '📆',
        'xp_reward': 300,
        'category': 'streak'
    },
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

    # Level milestones
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


def add_achievements():
    """Add new achievements to database"""
    app = create_app()

    with app.app_context():
        print("Adding new achievements...")

        added = 0
        skipped = 0

        for achievement_data in NEW_ACHIEVEMENTS:
            # Check if achievement already exists
            existing = Achievement.query.filter_by(code=achievement_data['code']).first()

            if existing:
                print(f"⚠️  Skipped '{achievement_data['name']}' (already exists)")
                skipped += 1
                continue

            # Add new achievement
            achievement = Achievement(**achievement_data)
            db.session.add(achievement)
            print(f"✓ Added '{achievement_data['name']}'")
            added += 1

        db.session.commit()

        print("\n" + "="*60)
        print("ACHIEVEMENTS UPDATE COMPLETED")
        print("="*60)
        print(f"Added: {added} new achievements")
        print(f"Skipped: {skipped} existing achievements")
        print(f"\nTotal achievements in database: {Achievement.query.count()}")


if __name__ == '__main__':
    add_achievements()
