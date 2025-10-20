#!/usr/bin/env python3
"""
Скрипт для запуска миграции модульной системы
"""
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.modules.migrations import run_migration

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        print("=" * 50)
        print("Запуск миграции модульной системы")
        print("=" * 50)
        run_migration()
        print("=" * 50)
        print("Миграция завершена успешно!")
        print("=" * 50)
