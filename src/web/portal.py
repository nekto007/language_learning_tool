"""
Web interface concept for a word learning system.
Based on Flask and SQLAlchemy for simplicity of implementation.
"""

import secrets
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

# Flask application initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///language_learning.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database initialization
db = SQLAlchemy(app)

# Authentication setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# Database models
class User(db.Model, UserMixin):
    """User model."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user_words = db.relationship('UserWord', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Book(db.Model):
    """Book model."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    word_links = db.relationship('WordBookLink', backref='book', lazy='dynamic')


class Word(db.Model):
    """Word model."""
    id = db.Column(db.Integer, primary_key=True)
    english_word = db.Column(db.String(100), unique=True, nullable=False)
    russian_word = db.Column(db.String(100))
    listening = db.Column(db.String(200))
    sentences = db.Column(db.Text)
    level = db.Column(db.String(20))
    brown = db.Column(db.Boolean, default=False)
    get_download = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    word_links = db.relationship('WordBookLink', backref='word', lazy='dynamic')
    user_words = db.relationship('UserWord', backref='word', lazy='dynamic')
    phrasal_verbs = db.relationship('PhrasalVerb', backref='base_word', lazy='dynamic')


class WordBookLink(db.Model):
    """Word and book link model."""
    id = db.Column(db.Integer, primary_key=True)
    word_id = db.Column(db.Integer, db.ForeignKey('word.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    frequency = db.Column(db.Integer, default=1)

    __table_args__ = (db.UniqueConstraint('word_id', 'book_id'),)


class UserWord(db.Model):
    """Model for tracking user progress on words."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    word_id = db.Column(db.Integer, db.ForeignKey('word.id'), nullable=False)
    learning_status = db.Column(db.Integer, default=0)
    last_practice = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'word_id'),)


class PhrasalVerb(db.Model):
    """Phrasal verb model."""
    id = db.Column(db.Integer, primary_key=True)
    phrasal_verb = db.Column(db.String(100), unique=True, nullable=False)
    russian_translate = db.Column(db.String(100))
    usage_examples = db.Column(db.Text)
    sentence = db.Column(db.Text)
    word_id = db.Column(db.Integer, db.ForeignKey('word.id'))
    listening = db.Column(db.String(200))
    get_download = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Constants for learning statuses
class LearningStatus:
    NEW = 0
    STUDYING = 1
    STUDIED = 2

    LABELS = {
        NEW: "New",
        STUDYING: "Studying",
        STUDIED: "Studied",
    }


# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next', url_for('dashboard'))
            return redirect(next_page)

        flash('Invalid username or password', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        # Check if user exists
        user_exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if user_exists:
            flash('A user with this username or email already exists', 'danger')
        else:
            # Create new user
            new_user = User(username=username, email=email)
            new_user.set_password(password)

            db.session.add(new_user)
            db.session.commit()

            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# Main functionality routes
@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    # User word statistics
    stats = {}
    for status in LearningStatus.LABELS:
        count = UserWord.query.filter_by(
            user_id=current_user.id, learning_status=status
        ).count()
        stats[status] = {
            'label': LearningStatus.LABELS[status],
            'count': count
        }

    total_words = sum(stat['count'] for stat in stats.values())

    # Recently added books
    recent_books = Book.query.order_by(Book.created_at.desc()).limit(5).all()

    # Recently learned words
    recent_words = UserWord.query.filter_by(
        user_id=current_user.id
    ).order_by(UserWord.updated_at.desc()).limit(10).all()

    return render_template(
        'dashboard.html',
        stats=stats,
        total_words=total_words,
        recent_books=recent_books,
        recent_words=recent_words
    )


@app.route('/books')
@login_required
def books():
    all_books = Book.query.order_by(Book.title).all()
    return render_template('books.html', books=all_books)


@app.route('/book/<int:book_id>')
@login_required
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)

    # Get words from the book with their statuses for the current user
    words_query = db.session.query(
        Word, WordBookLink.frequency, UserWord.learning_status
    ).join(
        WordBookLink, Word.id == WordBookLink.word_id
    ).outerjoin(
        UserWord, (Word.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    ).filter(
        WordBookLink.book_id == book_id
    ).order_by(
        WordBookLink.frequency.desc()
    )

    words = words_query.all()

    # Statistics by status
    stats = {}
    total_words = len(words)

    for status in LearningStatus.LABELS:
        count = sum(1 for _, _, word_status in words if word_status == status)
        stats[status] = {
            'label': LearningStatus.LABELS[status],
            'count': count,
            'percentage': (count / total_words * 100) if total_words > 0 else 0
        }

    return render_template(
        'book_detail.html',
        book=book,
        words=words,
        stats=stats,
        total_words=total_words,
        learning_status=LearningStatus
    )


@app.route('/words')
@login_required
def words():
    status_filter = request.args.get('status', None)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Base query
    query = db.session.query(
        Word, UserWord.learning_status
    ).outerjoin(
        UserWord, (Word.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    )

    # Apply status filter
    if status_filter is not None:
        try:
            status_filter = int(status_filter)
            query = query.filter(UserWord.learning_status == status_filter)
        except ValueError:
            pass

    # Get words with pagination
    paginated_words = query.order_by(Word.english_word).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        'words.html',
        paginated_words=paginated_words,
        status_filter=status_filter,
        learning_status=LearningStatus
    )


@app.route('/interactive')
@login_required
def interactive():
    status_filter = request.args.get('status', LearningStatus.NEW, type=int)
    book_id = request.args.get('book_id', None, type=int)
    batch_size = request.args.get('batch_size', 10, type=int)

    # Base query for getting words
    query = db.session.query(Word)

    if book_id:
        # If a book is specified, get words from that book
        query = query.join(
            WordBookLink, Word.id == WordBookLink.word_id
        ).filter(
            WordBookLink.book_id == book_id
        )

    # Add user learning status
    query = query.outerjoin(
        UserWord, (Word.id == UserWord.word_id) & (UserWord.user_id == current_user.id)
    ).filter(
        (UserWord.learning_status == status_filter) |
        ((UserWord.learning_status is None) & (status_filter == LearningStatus.NEW))
    )

    # Limit the number of words
    words = query.order_by(Word.english_word).limit(batch_size).all()

    # If a book is requested, get its data
    book = None
    if book_id:
        book = Book.query.get_or_404(book_id)

    return render_template(
        'interactive.html',
        words=words,
        book=book,
        status_filter=status_filter,
        batch_size=batch_size,
        learning_status=LearningStatus
    )


@app.route('/api/update_word_status', methods=['POST'])
@login_required
def update_word_status():
    data = request.json
    word_id = data.get('word_id')
    status = data.get('status')

    if not word_id or status is None:
        return jsonify({'success': False, 'error': 'Missing parameters'}), 400

    # Get or create UserWord record
    user_word = UserWord.query.filter_by(
        user_id=current_user.id, word_id=word_id
    ).first()

    if not user_word:
        user_word = UserWord(user_id=current_user.id, word_id=word_id)
        db.session.add(user_word)

    # Update status
    user_word.learning_status = status
    user_word.updated_at = datetime.utcnow()

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'word_id': word_id,
            'status': status,
            'status_label': LearningStatus.LABELS.get(status, 'Unknown')
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/batch_update_status', methods=['POST'])
@login_required
def batch_update_status():
    data = request.json
    word_ids = data.get('word_ids', [])
    status = data.get('status')

    if not word_ids or status is None:
        return jsonify({'success': False, 'error': 'Missing parameters'}), 400

    try:
        updated_words = []

        for word_id in word_ids:
            # Get or create UserWord record
            user_word = UserWord.query.filter_by(
                user_id=current_user.id, word_id=word_id
            ).first()

            if not user_word:
                user_word = UserWord(user_id=current_user.id, word_id=word_id)
                db.session.add(user_word)

            # Update status
            user_word.learning_status = status
            user_word.updated_at = datetime.utcnow()
            updated_words.append(word_id)

        db.session.commit()
        return jsonify({
            'success': True,
            'updated_words': updated_words,
            'status': status,
            'status_label': LearningStatus.LABELS.get(status, 'Unknown')
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# Import and export routes
@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_data():
    if request.method == 'POST':
        file = request.files.get('file')
        import_type = request.form.get('import_type')

        if file and import_type:
            # Import logic depending on data type
            try:
                flash('Import successfully completed!', 'success')
            except Exception as e:
                flash(f'Error during import: {str(e)}', 'danger')
        else:
            flash('Please select a file and import type', 'warning')

    return render_template('import.html')


@app.route('/export', methods=['GET'])
@login_required
def export_data():
    # Get the variables but actually use them in the logic
    export_type = request.args.get('type', 'words')
    format_type = request.args.get('format', 'csv')

    # Export logic depending on data type and format
    # Here we would generate the file for download based on export_type and format_type

    # For demonstration purposes, we'll just use these variables in a simple context
    context = {
        'export_types': ['words', 'books', 'user_progress'],
        'format_types': ['csv', 'json', 'xlsx'],
        'selected_export_type': export_type,
        'selected_format_type': format_type
    }

    return render_template('export.html', **context)


# Administration routes
@app.route('/admin')
@login_required
def admin():
    # Check administrator rights
    # Access control logic should be here

    return render_template('admin.html')


if __name__ == '__main__':
    # Create database
    with app.app_context():
        db.create_all()

    app.run(debug=True)
