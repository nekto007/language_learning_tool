# Для использования этих команд, создайте файл cli.py в корне проекта
# и импортируйте его в основном файле запуска (run.py)

import click
from flask import current_app
from flask.cli import with_appcontext
import os


@click.group()
def translate():
    """Translation and localization commands."""
    pass


@translate.command()
def extract():
    """Extract all messages for translation."""
    if not os.path.exists('babel.cfg'):
        print('Error: babel.cfg file not found')
        return

    # Убедимся, что директория для переводов существует
    if not os.path.exists('app/translations'):
        os.makedirs('app/translations')

    # Извлечение сообщений
    os.system('pybabel extract -F babel.cfg -o app/translations/messages.pot .')
    print('Extracted messages to messages.pot')


@translate.command()
@click.argument('lang')
def init(lang):
    """Initialize a new language."""
    if not os.path.exists('app/translations/messages.pot'):
        print('Error: messages.pot file not found. Run "flask translate extract" first')
        return

    # Инициализация нового языка
    os.system(f'pybabel init -i app/translations/messages.pot -d app/translations -l {lang}')
    print(f'Initialized translation for {lang}')


@translate.command()
def update():
    """Update all language catalogs."""
    if not os.path.exists('app/translations/messages.pot'):
        print('Error: messages.pot file not found. Run "flask translate extract" first')
        return

    # Обновление каталогов переводов
    os.system('pybabel update -i app/translations/messages.pot -d app/translations')
    print('Updated language catalogs')


@translate.command()
def compile():
    """Compile all language catalogs."""
    # Компиляция каталогов переводов
    os.system('pybabel compile -d app/translations')
    print('Compiled language catalogs')

# В файле run.py добавьте:
# from cli import translate
# app.cli.add_command(translate)