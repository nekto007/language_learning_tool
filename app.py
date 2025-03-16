"""
Flask web application for language learning.
"""
import logging
import os
import sqlite3
from functools import wraps

from flask import (
    Flask, flash, g, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for,
)

from admin import init_admin, make_user_admin
from config.settings import DB_FILE
from src.db.models import Word
from src.db.repository import DatabaseRepository
from src.user.repository import UserRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
admin, admin_db = init_admin(app, DB_FILE)
app.secret_key = os.environ.get("SECRET_KEY", "development_secret_key")

# Initialize repositories
db_repo = DatabaseRepository(DB_FILE)
user_repo = UserRepository(DB_FILE)

# Ensure user schema exists
user_repo.initialize_schema()


# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated_function


@app.before_request
def load_logged_in_user():
    """Load user data before each request if user is logged in."""
    user_id = session.get('user_id')

    if user_id is None:
        g.user = None
    else:
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Получаем базовую информацию о пользователе
            user = user_repo.get_user_by_id(user_id)

            if user:
                # Дополнительно проверяем is_admin
                cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
                admin_data = cursor.fetchone()

                if admin_data and 'is_admin' in admin_data.keys():
                    # Устанавливаем флаг администратора
                    user.is_admin = bool(admin_data['is_admin'])
                else:
                    user.is_admin = False

                g.user = user
            else:
                g.user = None

        except sqlite3.Error as e:
            logger.error(f"Database error in load_logged_in_user: {e}")
            g.user = None
        finally:
            conn.close()


@app.route('/')
def index():
    """Home page."""
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form.get('email')

        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'

        if error is None:
            user_id = user_repo.create_user(username, password, email)

            if user_id:
                flash('Registration successful! Please log in.', 'success')
                return redirect(url_for('login'))
            else:
                error = 'Username already exists.'

        flash(error, 'danger')

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = user_repo.authenticate_user(username, password)

        if user:
            session.clear()
            session['user_id'] = user.id
            session['username'] = user.username

            next_page = request.args.get('next')
            if not next_page or next_page.startswith('/'):
                next_page = url_for('dashboard')

            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page)

        flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """User logout."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard."""
    user_id = session['user_id']

    # Get word status statistics
    stats = user_repo.get_status_statistics(user_id)

    # Get books with statistics
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.title, b.total_words, b.unique_words, b.scrape_date,
                   COUNT(DISTINCT wbl.word_id) as linked_words,
                   SUM(wbl.frequency) as word_occurrences
            FROM book b
            LEFT JOIN word_book_link wbl ON b.id = wbl.book_id
            GROUP BY b.id, b.title
            ORDER BY b.title
        """)
        books = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Database error in dashboard: {e}")
        books = []
    finally:
        conn.close()

    return render_template(
        'dashboard.html',
        stats=stats,
        books=books,
        status_labels=Word.STATUS_LABELS,
    )


@app.route('/words')
@login_required
def words_list():
    """List all words with status."""
    user_id = session['user_id']
    status = request.args.get('status', type=int)
    book_id = request.args.get('book_id', type=int)
    letter = request.args.get('letter')
    page = request.args.get('page', 1, type=int)
    per_page = 50  # number of words per page
    show_all = request.args.get('show_all', type=int, default=0)  # parameter to show all words
    search_query = request.args.get('search', '')  # search query

    words = []
    book_title = None
    total_words = 0

    # Get word status statistics
    stats = user_repo.get_status_statistics(user_id)

    # Get word statuses using a direct connection to preserve cursor state
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Enable dictionary access
        cursor = conn.cursor()

        # НАЧАЛО ИЗМЕНЕНИЙ: Полностью переработанная логика формирования запроса

        # Базовые запросы
        if book_id:
            # Получаем название книги если указан book_id
            cursor.execute("SELECT title FROM book WHERE id = ?", (book_id,))
            book_result = cursor.fetchone()
            if book_result:
                book_title = book_result['title']

            base_query = """
                SELECT cw.*, COALESCE(uws.status, 0) as status, wbl.frequency
                FROM collections_word cw
                JOIN word_book_link wbl ON cw.id = wbl.word_id
                LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
                WHERE wbl.book_id = ?
            """
            base_count_query = """
                SELECT COUNT(*)
                FROM collections_word cw
                JOIN word_book_link wbl ON cw.id = wbl.word_id
                LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
                WHERE wbl.book_id = ?
            """
            base_params = [user_id, book_id]
            order_by = " ORDER BY wbl.frequency DESC"
        else:
            base_query = """
                SELECT cw.*, COALESCE(uws.status, 0) as status
                FROM collections_word cw
                LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
                WHERE 1=1  
            """
            base_count_query = """
                SELECT COUNT(*)
                FROM collections_word cw
                LEFT JOIN user_word_status uws ON cw.id = uws.word_id AND uws.user_id = ?
                WHERE 1=1
            """
            base_params = [user_id]
            if status is not None:
                order_by = " ORDER BY cw.english_word"
            else:
                order_by = " ORDER BY COALESCE(uws.status, 0), cw.english_word"

        # Собираем условия и параметры для запроса
        conditions = []
        params = list(base_params)  # Создаем копию базовых параметров

        # Фильтр для отображения слов только с русским переводом
        if not show_all:
            conditions.append("cw.russian_word IS NOT NULL AND cw.russian_word != ''")

        # Фильтр по статусу
        if status is not None:
            conditions.append("COALESCE(uws.status, 0) = ?")
            params.append(status)

        # Приоритет поиска над фильтром по букве
        if search_query:
            conditions.append("(cw.english_word LIKE ? OR cw.russian_word LIKE ?)")
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param])
        elif letter:  # Используем фильтр по букве только если нет поискового запроса
            conditions.append("LOWER(cw.english_word) LIKE ?")
            params.append(f"{letter.lower()}%")

        # Составляем финальный запрос с условиями
        query = base_query
        count_query = base_count_query

        if conditions:
            condition_str = " AND " + " AND ".join(conditions)
            query += condition_str
            count_query += condition_str

        # Получаем общее количество слов для пагинации
        cursor.execute(count_query, params)
        total_words = cursor.fetchone()[0]

        # Добавляем сортировку и пагинацию
        query += order_by + " LIMIT ? OFFSET ?"
        params.append(per_page)
        params.append((page - 1) * per_page)

        # Выполняем запрос
        cursor.execute(query, params)
        words = [dict(row) for row in cursor.fetchall()]

        # КОНЕЦ ИЗМЕНЕНИЙ

    except sqlite3.Error as e:
        flash(f"Database error: {e}", "danger")
        logger.error(f"Database error in words_list: {e}")
    finally:
        conn.close()

    # Calculate total pages
    total_pages = (total_words + per_page - 1) // per_page if total_words > 0 else 1

    return render_template(
        'words_list.html',
        words=words,
        status=status,
        book_id=book_id,
        book_title=book_title,
        status_labels=Word.STATUS_LABELS,
        stats=stats,
        letter=letter,
        page=page,
        total_pages=total_pages,
        total_words=total_words,
        show_all=show_all,
        search_query=search_query
    )


@app.route('/api/update-word-status', methods=['POST'])
@login_required
def update_word_status():
    """Update word status API endpoint."""
    user_id = session['user_id']
    word_id = request.json.get('word_id')
    status = request.json.get('status')

    if not word_id or status is None:
        return jsonify({'success': False, 'error': 'Missing word_id or status'}), 400

    success = user_repo.set_word_status(user_id, word_id, status)

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to update status'}), 500


@app.route('/api/batch-update-status', methods=['POST'])
@login_required
def batch_update_status():
    """Batch update word statuses API endpoint."""
    user_id = session['user_id']
    word_ids = request.json.get('word_ids', [])
    status = request.json.get('status')

    if not word_ids or status is None:
        return jsonify({'success': False, 'error': 'Missing word_ids or status'}), 400

    success_count = 0
    for word_id in word_ids:
        if user_repo.set_word_status(user_id, word_id, status):
            success_count += 1

    return jsonify({
        'success': True,
        'updated_count': success_count,
        'total_count': len(word_ids)
    })


@app.route('/word/<int:word_id>')
@login_required
def word_detail(word_id):
    """Word detail page."""
    user_id = session['user_id']

    # Get word details using direct connection
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Enable dictionary access
        cursor = conn.cursor()

        # Get word details
        cursor.execute("SELECT * FROM collections_word WHERE id = ?", (word_id,))
        word_result = cursor.fetchone()

        if not word_result:
            flash('Word not found.', 'danger')
            return redirect(url_for('words_list'))

        word = dict(word_result)

        # Get word status
        cursor.execute(
            "SELECT status FROM user_word_status WHERE user_id = ? AND word_id = ?",
            (user_id, word_id)
        )
        status_result = cursor.fetchone()
        status = status_result['status'] if status_result else Word.STATUS_NEW

        word['status'] = status

        # Get books containing this word
        cursor.execute("""
            SELECT b.id, b.title, wbl.frequency
            FROM book b
            JOIN word_book_link wbl ON b.id = wbl.book_id
            WHERE wbl.word_id = ?
            ORDER BY wbl.frequency DESC
        """, (word_id,))

        books = [dict(row) for row in cursor.fetchall()]

    except sqlite3.Error as e:
        flash(f"Database error: {e}", "danger")
        logger.error(f"Database error in word_detail: {e}")
        books = []
        word = {"english_word": "Error loading word", "status": Word.STATUS_NEW}
    finally:
        conn.close()

    return render_template(
        'word_detail.html',
        word=word,
        books=books,
        status_labels=Word.STATUS_LABELS,
    )


@app.template_filter('status_badge')
def status_badge(status):
    """Template filter to render status as a badge."""
    classes = {
        Word.STATUS_NEW: 'badge bg-secondary',
        Word.STATUS_QUEUED: 'badge bg-info',
        Word.STATUS_ACTIVE: 'badge bg-primary',
        Word.STATUS_MASTERED: 'badge bg-warning',
    }

    label = Word.STATUS_LABELS.get(status, 'Unknown')
    badge_class = classes.get(status, 'badge bg-secondary')

    return f'<span class="{badge_class}">{label}</span>'


@app.route('/static/media/<path:filename>')
def serve_media(filename):
    """Serve pronunciation files from the Anki media folder."""
    # Configure this path to match your actual Anki media folder
    anki_media_path = os.path.expanduser('~/Library/Application Support/Anki2/User 1/collection.media')

    # For Windows, you might use something like:
    # anki_media_path = os.path.join(os.environ['APPDATA'], 'Anki2', 'User 1', 'collection.media')

    # For Linux:
    # anki_media_path = os.path.expanduser('~/.local/share/Anki2/User 1/collection.media')

    return send_from_directory(anki_media_path, filename)


@app.route('/api/export-anki', methods=['POST'])
@login_required
def export_anki():
    """API endpoint for exporting words to Anki deck."""
    user_id = session['user_id']

    try:
        # Get export settings from request
        export_settings = request.json
        deck_name = export_settings.get('deckName', 'English Words')
        card_format = export_settings.get('cardFormat', 'basic')
        include_pronunciation = export_settings.get('includePronunciation', True)
        include_examples = export_settings.get('includeExamples', True)
        update_status = export_settings.get('updateStatus', False)
        word_ids = export_settings.get('wordIds', [])

        if not word_ids:
            return jsonify({'success': False, 'error': 'No words selected'}), 400

        # Get word data
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Create a temporary file for the deck
            import tempfile
            import genanki
            import random
            import time
            import os

            # Create a unique model ID (based on timestamp)
            model_id = random.randrange(1 << 30, 1 << 31)

            # CSS styles for cards
            card_css = """
.card {
        font-family: arial;
        font-size: 20px;
        text-align: center;
        color: black;
        background-color:
        white;
        }
    .from {
        font-style: italic;
    }
            """

            # Front side template
            front_template = """
    <strong>{{en}}</strong>
    
    <br><br>
    {{sound_name}}
            """

            # Back side template
            back_template = """
{{FrontSide}}
<hr id=answer>
<font color="red">{{ru}}</font>
<br><br>
<em>{{text:context}}</em>
            """

            # Define the card model with new field names and templates
            model = genanki.Model(
                model_id,
                'English Word',
                fields=[
                    {'name': 'en'},
                    {'name': 'ru'},
                    {'name': 'sound_name'},
                    {'name': 'context'},
                ],
                templates=[
                    {
                        'name': 'English to Russian',
                        'qfmt': front_template,
                        'afmt': back_template,
                    },
                ],
                css=card_css
            )

            # Create deck
            deck = genanki.Deck(
                random.randrange(1 << 30, 1 << 31),
                deck_name
            )

            # Create a package for the deck
            package = genanki.Package(deck)
            media_files = []

            # Get word data and create notes
            placeholders = ','.join(['?'] * len(word_ids))
            cursor.execute(f'''
                SELECT cw.* 
                FROM collections_word cw
                WHERE cw.id IN ({placeholders})
            ''', word_ids)

            words = cursor.fetchall()

            # Get Anki media folder path
            anki_media_path = None
            if include_pronunciation:
                if os.path.exists(os.path.expanduser('~/Library/Application Support/Anki2/User 1/collection.media')):
                    anki_media_path = os.path.expanduser('~/Library/Application Support/Anki2/User 1/collection.media')
                elif os.path.exists(os.path.join(os.environ.get('APPDATA', ''), 'Anki2/User 1/collection.media')):
                    anki_media_path = os.path.join(os.environ.get('APPDATA', ''), 'Anki2/User 1/collection.media')
                elif os.path.exists(os.path.expanduser('~/.local/share/Anki2/User 1/collection.media')):
                    anki_media_path = os.path.expanduser('~/.local/share/Anki2/User 1/collection.media')

            for word in words:
                english = word['english_word']
                russian = word['russian_word'] or ''

                # Handle pronunciation
                sound_html = ''
                if include_pronunciation and word['get_download'] == 1 and anki_media_path:
                    # Sound file name
                    sound_file = f"pronunciation_en_{english.lower().replace(' ', '_')}.mp3"
                    sound_path = os.path.join(anki_media_path, sound_file)

                    if os.path.exists(sound_path):
                        sound_html = f'[sound:{sound_file}]'
                        # Add file to media files
                        media_files.append(sound_path)

                # Handle example sentences
                context_html = ''
                if include_examples and word['sentences']:
                    context_html = word['sentences']

                # Create note with new field names
                note = genanki.Note(
                    model=model,
                    fields=[english, russian, sound_html, context_html]
                )

                deck.add_note(note)

                # Update word status if requested
                if update_status:
                    user_repo.set_word_status(user_id, word['id'], Word.STATUS_ACTIVE)

            # Create a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.apkg') as temp_file:
                temp_path = temp_file.name

            # Generate and save the package
            package.media_files = media_files
            package.write_to_file(temp_path)

            # Return the file for download
            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f"{deck_name}.apkg",
                mimetype='application/octet-stream'
            )

        except sqlite3.Error as e:
            logger.error(f"Database error in export_anki: {e}")
            return jsonify({'success': False, 'error': f'Database error: {e}'}), 500
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error in export_anki: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/setup-admin/<username>/<secret_key>')
def setup_admin(username, secret_key):
    """Assigns user as administrator(secret key required)."""
    # Compare to the secret key set in environment variables or settings
    actual_secret = os.environ.get("ADMIN_SETUP_KEY", "change_this_to_secure_key")

    if secret_key != actual_secret:
        flash('Invalid secret key.', 'danger')
        return redirect(url_for('index'))

    if make_user_admin(DB_FILE, username):
        flash(f'User {username} has been made an administrator.', 'success')
    else:
        flash(f'Failed to assign user {username} as administrator.', 'danger')

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
