#!/usr/bin/env python3
"""
CLI скрипт для безопасного создания первого администратора

Использование:
    # Интерактивный режим:
    python create_admin.py

    # Через переменные окружения:
    ADMIN_USERNAME=admin ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=SecurePass123! python create_admin.py

    # Через аргументы командной строки:
    python create_admin.py --username admin --email admin@example.com --password SecurePass123!
"""
import argparse
import getpass
import os
import sys
from datetime import datetime, timezone

# Добавляем корневую директорию в путь для импорта модулей приложения
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.auth.models import User
from app.utils.db import db
from app.utils.password_validator import validate_password_strength


def get_input_with_validation(prompt: str, validator=None, hide_input: bool = False) -> str:
    """Получает ввод пользователя с валидацией"""
    while True:
        if hide_input:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt).strip()

        if not value:
            print("❌ Значение не может быть пустым. Попробуйте снова.")
            continue

        if validator:
            is_valid, errors = validator(value)
            if not is_valid:
                print("❌ Ошибки валидации:")
                for error in errors:
                    print(f"   - {error}")
                print("Попробуйте снова.\n")
                continue

        return value


def create_admin_user(username: str = None, email: str = None, password: str = None, force: bool = False):
    """
    Создает администратора

    Args:
        username: Имя пользователя (если None, запрашивается интерактивно)
        email: Email (если None, запрашивается интерактивно)
        password: Пароль (если None, запрашивается интерактивно)
        force: Принудительное создание даже если админ уже существует
    """
    print("\n" + "=" * 60)
    print("  СОЗДАНИЕ АДМИНИСТРАТОРА")
    print("=" * 60 + "\n")

    app = create_app()

    with app.app_context():
        # Проверяем, есть ли уже администратор
        existing_admin = User.query.filter_by(is_admin=True).first()
        if existing_admin and not force:
            print(f"⚠️  Администратор уже существует: {existing_admin.username} ({existing_admin.email})")
            response = input("\nВы хотите создать еще одного администратора? (yes/no): ").strip().lower()
            if response not in ['yes', 'y', 'да']:
                print("❌ Отменено.")
                sys.exit(0)

        # Получаем username
        if not username:
            username = get_input_with_validation(
                "Введите имя пользователя (username): ",
                validator=lambda u: (len(u) >= 3, ["Минимум 3 символа"])
            )

        # Проверяем уникальность username
        if User.query.filter_by(username=username).first():
            print(f"❌ Пользователь с именем '{username}' уже существует!")
            sys.exit(1)

        # Получаем email
        if not email:
            def email_validator(e):
                if '@' not in e or '.' not in e.split('@')[1]:
                    return False, ["Неверный формат email"]
                if User.query.filter_by(email=e).first():
                    return False, [f"Email '{e}' уже используется"]
                return True, []

            email = get_input_with_validation(
                "Введите email: ",
                validator=email_validator
            )
        else:
            # Проверяем уникальность email
            if User.query.filter_by(email=email).first():
                print(f"❌ Email '{email}' уже используется!")
                sys.exit(1)

        # Получаем пароль
        if not password:
            print("\nТребования к паролю:")
            print("  • Минимум 8 символов")
            print("  • Хотя бы одна заглавная буква")
            print("  • Хотя бы одна строчная буква")
            print("  • Хотя бы одна цифра")
            print("  • Рекомендуется специальный символ (!@#$%^&*)\n")

            def password_validator(p):
                return validate_password_strength(p, username, email)

            password = get_input_with_validation(
                "Введите пароль: ",
                validator=password_validator,
                hide_input=True
            )

            # Подтверждение пароля
            password_confirm = getpass.getpass("Подтвердите пароль: ")
            if password != password_confirm:
                print("❌ Пароли не совпадают!")
                sys.exit(1)
        else:
            # Валидация пароля из переменных окружения/аргументов
            is_valid, errors = validate_password_strength(password, username, email)
            if not is_valid:
                print("❌ Пароль не соответствует требованиям безопасности:")
                for error in errors:
                    print(f"   - {error}")
                sys.exit(1)

        # Создаем администратора
        try:
            admin_user = User(
                username=username,
                email=email,
                is_admin=True,
                active=True,
                created_at=datetime.now(timezone.utc)
            )
            admin_user.set_password(password)

            db.session.add(admin_user)
            db.session.commit()

            print("\n" + "=" * 60)
            print("✅ Администратор успешно создан!")
            print("=" * 60)
            print(f"Username: {username}")
            print(f"Email:    {email}")
            print(f"Admin:    Yes")
            print("=" * 60 + "\n")

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Ошибка при создании администратора: {str(e)}")
            sys.exit(1)


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Создание администратора для приложения',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:

  Интерактивный режим:
    python create_admin.py

  Через переменные окружения:
    ADMIN_USERNAME=admin ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=SecurePass123! python create_admin.py

  Через аргументы командной строки:
    python create_admin.py --username admin --email admin@example.com --password SecurePass123!

  Принудительное создание (даже если админ уже существует):
    python create_admin.py --force
        """
    )

    parser.add_argument('--username', '-u', help='Имя пользователя')
    parser.add_argument('--email', '-e', help='Email')
    parser.add_argument('--password', '-p', help='Пароль (небезопасно - используйте переменные окружения)')
    parser.add_argument('--force', '-f', action='store_true', help='Создать даже если админ уже существует')

    args = parser.parse_args()

    # Проверяем переменные окружения
    username = args.username or os.getenv('ADMIN_USERNAME')
    email = args.email or os.getenv('ADMIN_EMAIL')
    password = args.password or os.getenv('ADMIN_PASSWORD')

    # Предупреждение о небезопасном использовании пароля в CLI
    if args.password:
        print("⚠️  ПРЕДУПРЕЖДЕНИЕ: Передача пароля через аргумент командной строки небезопасна!")
        print("    Используйте переменные окружения или интерактивный режим.\n")

    create_admin_user(username, email, password, args.force)


if __name__ == '__main__':
    main()