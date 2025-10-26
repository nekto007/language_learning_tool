#!/usr/bin/env python3
"""
Скрипт для первоначальной синхронизации мастер-колод для всех пользователей
"""
from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():
    # Импортируем функцию синхронизации
    from app.study.routes import sync_master_decks

    # Получаем всех пользователей
    users = User.query.all()

    print(f"Найдено пользователей: {len(users)}")

    for user in users:
        print(f"Синхронизация для пользователя: {user.username} (ID: {user.id})")
        try:
            sync_master_decks(user.id)
            db.session.commit()
            print(f"  ✓ Успешно")
        except Exception as e:
            print(f"  ✗ Ошибка: {e}")
            db.session.rollback()

    print("\nГотово!")
