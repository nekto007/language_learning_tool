from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_sqlalchemy import SQLAlchemy


def init_admin(app, db_file_path):
    """Простая инициализация админки без сложных настроек"""

    # Настройка SQLAlchemy
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_file_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'check_same_thread': False}
    }

    # Инициализация SQLAlchemy
    db = SQLAlchemy(app)

    # Простые модели
    class User(db.Model):
        __tablename__ = 'users'
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String)
        email = db.Column(db.String)
        is_admin = db.Column(db.Boolean)

    class Word(db.Model):
        __tablename__ = 'collections_word'
        id = db.Column(db.Integer, primary_key=True)
        english_word = db.Column(db.String)
        russian_word = db.Column(db.String)

    class Book(db.Model):
        __tablename__ = 'book'
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String)

    # Инициализация Admin
    admin = Admin(app, name='Admin Panel', template_mode='bootstrap3')

    # Добавление представлений
    admin.add_view(ModelView(User, db.session))
    admin.add_view(ModelView(Word, db.session))
    admin.add_view(ModelView(Book, db.session))

    return admin, db


def make_user_admin(db_file_path, username):
    """Простая функция для назначения пользователя администратором"""
    import sqlite3

    try:
        with sqlite3.connect(db_file_path) as conn:
            cursor = conn.cursor()

            # Проверка наличия колонки is_admin
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'is_admin' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

            # Назначение пользователя администратором
            cursor.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (username,))
            conn.commit()
            return True
    except Exception as e:
        print(f"Error: {e}")
        return False
