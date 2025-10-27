"""
Миграция для создания модульной системы.
Этот файл содержит SQL-скрипты для создания таблиц modules и user_modules.
"""

from app.utils.db import db
from app.modules.models import SystemModule, UserModule


def create_module_tables():
    """
    Создает таблицы для модульной системы
    """
    # SQLAlchemy автоматически создаст таблицы через db.create_all()
    # Но мы можем добавить кастомные миграции здесь, если нужно
    db.create_all()


def seed_initial_modules():
    """
    Заполняет таблицу modules начальными данными
    """
    # Проверяем, есть ли уже модули
    if SystemModule.query.count() > 0:
        return

    # Определяем начальные модули
    initial_modules = [
        {
            'code': 'curriculum',
            'name': 'Учебная программа',
            'description': 'Структурированная программа обучения с уровнями и уроками',
            'icon': 'graduation-cap',
            'is_active': True,
            'is_default': False,  # Опциональный модуль
            'order': 1,
            'blueprint_name': 'curriculum',
            'url_prefix': '/curriculum'
        },
        {
            'code': 'words',
            'name': 'Словарь',
            'description': 'Коллекция слов для изучения и повторения',
            'icon': 'book',
            'is_active': True,
            'is_default': True,  # Подключается автоматически при регистрации
            'order': 2,
            'blueprint_name': 'words',
            'url_prefix': '/words'
        },
        {
            'code': 'books',
            'name': 'Книги',
            'description': 'Чтение книг с возможностью изучения новых слов',
            'icon': 'book-open',
            'is_active': True,
            'is_default': False,  # Опциональный модуль
            'order': 3,
            'blueprint_name': 'books',
            'url_prefix': '/books'
        },
        {
            'code': 'study',
            'name': 'Повторение',
            'description': 'Система интервального повторения слов',
            'icon': 'brain',
            'is_active': True,
            'is_default': True,  # Подключается автоматически при регистрации
            'order': 4,
            'blueprint_name': 'study',
            'url_prefix': '/study'
        },
        {
            'code': 'reminders',
            'name': 'Напоминания',
            'description': 'Система напоминаний для регулярного обучения',
            'icon': 'bell',
            'is_active': True,
            'is_default': False,  # Опциональный модуль
            'order': 5,
            'blueprint_name': 'reminders',
            'url_prefix': '/reminders'
        },
    ]

    # Создаем модули
    for module_data in initial_modules:
        module = SystemModule(**module_data)
        db.session.add(module)

    db.session.commit()


def migrate_existing_users():
    """
    Мигрирует существующих пользователей, выдавая им дефолтные модули
    """
    from app.auth.models import User

    # Получаем всех пользователей
    users = User.query.all()

    # Получаем дефолтные модули
    default_modules = SystemModule.query.filter_by(is_default=True, is_active=True).all()

    migrated_count = 0
    for user in users:
        # Проверяем, есть ли у пользователя уже модули
        existing_modules = UserModule.query.filter_by(user_id=user.id).count()
        if existing_modules > 0:
            continue

        # Выдаем дефолтные модули
        for module in default_modules:
            user_module = UserModule(
                user_id=user.id,
                module_id=module.id,
                is_enabled=True,
                granted_by_admin=False
            )
            db.session.add(user_module)

        migrated_count += 1

    db.session.commit()


def run_migration():
    """
    Запускает полную миграцию
    """

    # Создаем таблицы
    create_module_tables()

    # Заполняем начальными модулями
    seed_initial_modules()

    # Мигрируем существующих пользователей
    migrate_existing_users()



if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        run_migration()
