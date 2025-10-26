"""
Migration script to add XP system and achievements tables.
Run this script to create the new tables and populate initial achievements.
"""
import os
import sys

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.utils.db import db
from app.study.models import UserXP, Achievement, UserAchievement

# Initial achievements to populate
INITIAL_ACHIEVEMENTS = [
    {
        'code': 'first_quiz',
        'name': 'Первый квиз',
        'description': 'Завершите свой первый квиз',
        'icon': '🎯',
        'xp_reward': 50,
        'category': 'quiz'
    },
    {
        'code': 'perfect_score',
        'name': 'Идеальный результат',
        'description': 'Получите 100% в квизе',
        'icon': '💯',
        'xp_reward': 100,
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
    {
        'code': 'quiz_streak_5',
        'name': 'Серия из 5',
        'description': 'Ответьте правильно на 5 вопросов подряд',
        'icon': '🔥',
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
        'code': 'high_score_90',
        'name': 'Отличник',
        'description': 'Получите 90%+ в квизе из 10+ вопросов',
        'icon': '⭐',
        'xp_reward': 50,
        'category': 'quiz'
    },
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
    {
        'code': 'daily_streak_7',
        'name': 'Неделя подряд',
        'description': 'Занимайтесь 7 дней подряд',
        'icon': '📅',
        'xp_reward': 150,
        'category': 'streak'
    },
    {
        'code': 'daily_streak_30',
        'name': 'Месяц подряд',
        'description': 'Занимайтесь 30 дней подряд',
        'icon': '🗓️',
        'xp_reward': 500,
        'category': 'streak'
    },
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
]


def run_migration():
    """Create tables and populate initial data"""
    app = create_app()

    with app.app_context():
        print("Creating XP system tables...")

        # Create tables
        db.create_all()
        print("✓ Tables created successfully")

        # Check if achievements already exist
        existing = Achievement.query.count()
        if existing > 0:
            print(f"⚠️  Found {existing} existing achievements. Skipping initial data.")
            return

        # Populate initial achievements
        print("Populating initial achievements...")
        for achievement_data in INITIAL_ACHIEVEMENTS:
            achievement = Achievement(**achievement_data)
            db.session.add(achievement)

        db.session.commit()
        print(f"✓ Added {len(INITIAL_ACHIEVEMENTS)} achievements")

        # Show summary
        print("\n" + "="*60)
        print("XP SYSTEM MIGRATION COMPLETED SUCCESSFULLY")
        print("="*60)
        print(f"Tables created: user_xp, achievements, user_achievements")
        print(f"Achievements added: {len(INITIAL_ACHIEVEMENTS)}")
        print("\nAchievement categories:")
        categories = {}
        for ach in INITIAL_ACHIEVEMENTS:
            cat = ach['category']
            categories[cat] = categories.get(cat, 0) + 1
        for cat, count in categories.items():
            print(f"  - {cat}: {count}")
        print("="*60)


if __name__ == '__main__':
    run_migration()
