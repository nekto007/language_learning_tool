# Для использования этих команд, создайте файл cli.py в корне проекта
# и импортируйте его в основном файле запуска (run.py)

import re
import subprocess

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
    subprocess.run(
        ['pybabel', 'extract', '-F', 'babel.cfg', '-o', 'app/translations/messages.pot', '.'],
        check=True
    )
    print('Extracted messages to messages.pot')


@translate.command()
@click.argument('lang')
def init(lang):
    """Initialize a new language."""
    if not os.path.exists('app/translations/messages.pot'):
        print('Error: messages.pot file not found. Run "flask translate extract" first')
        return

    # SECURITY: Validate lang to prevent command injection
    if not re.match(r'^[a-zA-Z_]{2,10}$', lang):
        print(f'Error: invalid language code "{lang}"')
        return

    # Инициализация нового языка
    subprocess.run(
        ['pybabel', 'init', '-i', 'app/translations/messages.pot', '-d', 'app/translations', '-l', lang],
        check=True
    )
    print(f'Initialized translation for {lang}')


@translate.command()
def update():
    """Update all language catalogs."""
    if not os.path.exists('app/translations/messages.pot'):
        print('Error: messages.pot file not found. Run "flask translate extract" first')
        return

    # Обновление каталогов переводов
    subprocess.run(
        ['pybabel', 'update', '-i', 'app/translations/messages.pot', '-d', 'app/translations'],
        check=True
    )
    print('Updated language catalogs')


@translate.command()
def compile():
    """Compile all language catalogs."""
    # Компиляция каталогов переводов
    subprocess.run(
        ['pybabel', 'compile', '-d', 'app/translations'],
        check=True
    )
    print('Compiled language catalogs')

# В файле run.py добавьте:
# from cli import translate
# app.cli.add_command(translate)
