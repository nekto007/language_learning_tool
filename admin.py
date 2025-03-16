"""
Admin interface for Language Learning Tool.
"""
import os
import sqlite3
import logging
from functools import wraps
from datetime import datetime
from flask import Flask, redirect, url_for, request, flash, g, session
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_sqlalchemy import SQLAlchemy
from wtforms.fields import PasswordField

# For logging
logger = logging.getLogger(__name__)

# Global variable for database path
db_path = None


# Decorator for checking admin rights
def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        # Check authentication
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))

        # Check admin rights
        user_id = session.get('user_id')
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            if not user or not user['is_admin']:
                flash('You do not have permission to access the admin interface.', 'danger')
                return redirect(url_for('index'))

        return func(*args, **kwargs)

    return decorated_view


# Custom AdminIndexView with rights check
class MyAdminIndexView(AdminIndexView):
    @expose('/')
    @admin_required
    def index(self):
        return self.render('admin/index.html')


# Secure model view
class SecureModelView(ModelView):
    def is_accessible(self):
        if 'user_id' not in session:
            return False

        user_id = session.get('user_id')
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            return user and user['is_admin']

    def inaccessible_callback(self, name, **kwargs):
        flash('You do not have permission to access the admin interface.', 'danger')
        return redirect(url_for('login', next=request.url))


def init_admin(app, db_file_path):
    """
    Initialize the admin interface.

    Args:
        app (Flask): Flask application instance
        db_file_path (str): Path to SQLite database file
    """
    global db_path
    db_path = db_file_path

    # SQLAlchemy configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_file_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'check_same_thread': False}
    }

    # Initialize SQLAlchemy
    db = SQLAlchemy(app)

    # Model definitions
    class User(db.Model):
        __tablename__ = 'users'
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String, nullable=False)
        password_hash = db.Column(db.String)
        salt = db.Column(db.String)
        email = db.Column(db.String)
        created_at = db.Column(db.DateTime)
        last_login = db.Column(db.DateTime)
        is_admin = db.Column(db.Boolean, default=False)

        def __repr__(self):
            return self.username

    class Word(db.Model):
        __tablename__ = 'collections_word'
        id = db.Column(db.Integer, primary_key=True)
        english_word = db.Column(db.String, nullable=False)
        russian_word = db.Column(db.String)
        listening = db.Column(db.String)
        sentences = db.Column(db.Text)
        level = db.Column(db.String)
        brown = db.Column(db.Integer, default=0)
        get_download = db.Column(db.Integer, default=0)
        learning_status = db.Column(db.Integer, default=0)

        def __repr__(self):
            return self.english_word

    class Book(db.Model):
        __tablename__ = 'book'
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String, nullable=False)
        total_words = db.Column(db.Integer, default=0)
        unique_words = db.Column(db.Integer, default=0)
        scrape_date = db.Column(db.DateTime)

        def __repr__(self):
            return self.title

    class UserWordStatus(db.Model):
        __tablename__ = 'user_word_status'
        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
        word_id = db.Column(db.Integer, db.ForeignKey('collections_word.id'), nullable=False)
        status = db.Column(db.Integer, default=0, nullable=False)
        last_updated = db.Column(db.DateTime)

        # Relationships
        user = db.relationship('User', backref=db.backref('word_statuses', lazy='dynamic'))
        word = db.relationship('Word', backref=db.backref('user_statuses', lazy='dynamic'))

        def __repr__(self):
            return f"Status {self.status}"

    class WordBookLink(db.Model):
        __tablename__ = 'word_book_link'
        id = db.Column(db.Integer, primary_key=True)
        word_id = db.Column(db.Integer, db.ForeignKey('collections_word.id'), nullable=False)
        book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
        frequency = db.Column(db.Integer, default=1)

        # Relationships
        word = db.relationship('Word', backref=db.backref('book_links', lazy='dynamic'))
        book = db.relationship('Book', backref=db.backref('word_links', lazy='dynamic'))

        def __repr__(self):
            return f"Link (freq: {self.frequency})"

    class PhrasalVerb(db.Model):
        __tablename__ = 'phrasal_verb'
        id = db.Column(db.Integer, primary_key=True)
        phrasal_verb = db.Column(db.String, nullable=False)
        russian_translate = db.Column(db.String)
        using = db.Column(db.String)
        sentence = db.Column(db.String)
        word_id = db.Column(db.Integer, db.ForeignKey('collections_word.id'))
        listening = db.Column(db.String)
        get_download = db.Column(db.Integer, default=0)

        # Relationship to word
        word = db.relationship('Word')

        def __repr__(self):
            return self.phrasal_verb

    # Add is_admin column to users table if it doesn't exist
    try:
        with sqlite3.connect(db_file_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'is_admin' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
                conn.commit()
                logging.info("Added is_admin column to users table")
    except sqlite3.Error as e:
        logging.error(f"Error adding is_admin column: {e}")

    # Model view configurations
    class UserView(SecureModelView):
        column_list = ('id', 'username', 'email', 'created_at', 'last_login', 'is_admin')
        column_searchable_list = ('username', 'email')
        column_filters = ('is_admin',)
        form_excluded_columns = ('password_hash', 'salt', 'word_statuses', 'created_at', 'last_login')
        form_extra_fields = {
            'password': PasswordField('Password')
        }
        column_labels = {
            'username': 'Username',
            'email': 'Email',
            'created_at': 'Created',
            'last_login': 'Last Login',
            'is_admin': 'Admin',
            'password': 'Password'
        }

        def on_model_change(self, form, model, is_created):
            # If creating a new user or changed password
            if hasattr(form, 'password') and form.password.data:
                # Import password hashing method from User model
                from src.user.models import User as UserModel

                # Hash password
                pw_hash, salt = UserModel.hash_password(form.password.data)
                model.password_hash = pw_hash
                model.salt = salt

                # Set current date for new users
                if is_created:
                    model.created_at = datetime.now()

    class WordView(SecureModelView):
        column_list = ('id', 'english_word', 'russian_word', 'level', 'get_download', 'learning_status')
        column_searchable_list = ['english_word',
                                  'russian_word']
        column_filters = ('learning_status', 'get_download', 'brown')
        column_labels = {
            'english_word': 'English Word',
            'russian_word': 'Translation',
            'listening': 'Audio URL',
            'sentences': 'Examples',
            'level': 'Level',
            'brown': 'Brown Corpus',
            'get_download': 'Pronunciation Downloaded',
            'learning_status': 'Learning Status'
        }

    class BookView(SecureModelView):
        column_list = ('id', 'title', 'total_words', 'unique_words', 'scrape_date')
        column_searchable_list = ('title',)
        column_labels = {
            'title': 'Title',
            'total_words': 'Total Words',
            'unique_words': 'Unique Words',
            'scrape_date': 'Scrape Date'
        }

    class UserWordStatusView(SecureModelView):
        column_list = ('id', 'user', 'word', 'status', 'last_updated')
        column_filters = ('status',)
        column_labels = {
            'user': 'User',
            'word': 'Word',
            'status': 'Status',
            'last_updated': 'Updated'
        }

    class WordBookLinkView(SecureModelView):
        column_list = ('id', 'word', 'book', 'frequency')
        column_labels = {
            'word': 'Word',
            'book': 'Book',
            'frequency': 'Frequency'
        }

    class PhrasalVerbView(SecureModelView):
        column_list = ('id', 'phrasal_verb', 'russian_translate', 'get_download')
        column_searchable_list = ('phrasal_verb', 'russian_translate')
        column_filters = ('get_download',)
        column_labels = {
            'phrasal_verb': 'Phrasal Verb',
            'russian_translate': 'Translation',
            'using': 'Usage',
            'sentence': 'Example',
            'word': 'Related Word',
            'listening': 'Audio URL',
            'get_download': 'Pronunciation Downloaded'
        }

    # Initialize Admin
    admin = Admin(
        app,
        name='Language Learning Tool Admin',
        template_mode='bootstrap3',
        index_view=MyAdminIndexView(name='Dashboard', url='/admin')
    )

    # Add model views
    admin.add_view(UserView(User, db.session))
    admin.add_view(WordView(Word, db.session))
    admin.add_view(BookView(Book, db.session))
    admin.add_view(UserWordStatusView(UserWordStatus, db.session))
    admin.add_view(WordBookLinkView(WordBookLink, db.session))
    admin.add_view(PhrasalVerbView(PhrasalVerb, db.session))

    return admin, db


def make_user_admin(db_file_path, username):
    """
    Grant admin rights to a user.

    Args:
        db_file_path (str): Path to SQLite database file
        username (str): Username to make admin

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with sqlite3.connect(db_file_path) as conn:
            cursor = conn.cursor()

            # Check if user exists
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()

            if not user:
                logging.error(f"User {username} not found")
                return False

            # Check if is_admin column exists
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]

            # Add is_admin column if it doesn't exist
            if 'is_admin' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")

            # Make user admin
            cursor.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (username,))
            conn.commit()

            logging.info(f"User {username} has been granted admin rights")
            return True
    except sqlite3.Error as e:
        logging.error(f"Error making user admin: {e}")
        return False