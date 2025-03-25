"""
Flask routes for SRS (Spaced Repetition System) functionality.
"""
import csv
import logging
import os
import tempfile
import uuid
from datetime import timedelta, datetime
from functools import wraps

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request,
    session, url_for,
)

from src.srs.service import SRSService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Blueprint
srs_bp = Blueprint('srs', __name__, url_prefix='/srs')

# Initialize service in app context
srs_service = None


def init_srs_service(db_path):
    """Initialize SRS service with database path."""
    global srs_service
    srs_service = SRSService(db_path)


# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def prepare_cards_for_template(cards):
    """
    Prepare card objects for template serialization by ensuring all values are JSON-serializable.

    Args:
        cards (list): List of card dictionaries

    Returns:
        list: List with all values converted to JSON-serializable types
    """
    import json
    from datetime import date, datetime

    serializable_cards = []

    for card in cards:
        # Create a new dictionary to hold serializable values
        serializable_card = {}

        for key, value in card.items():
            # Handle date and datetime objects
            if isinstance(value, (date, datetime)):
                serializable_card[key] = value.isoformat()
            # Handle other non-serializable types if needed
            elif isinstance(value, complex):
                serializable_card[key] = str(value)
            else:
                serializable_card[key] = value

        serializable_cards.append(serializable_card)

    # Test if the result is JSON-serializable
    try:
        json.dumps(serializable_cards)
    except TypeError as e:
        raise ValueError(f"Cards contain non-serializable values: {e}")

    return serializable_cards


# === Web Routes ===

@srs_bp.route('/api/import/file', methods=['POST'])
@login_required
def api_import_file():
    """API: Import deck from file (CSV, TXT, or APKG)."""
    user_id = session['user_id']

    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'error': 'No file part'
        }), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({
            'success': False,
            'error': 'No selected file'
        }), 400

    deck_name = request.form.get('deck_name', '')
    if not deck_name:
        return jsonify({
            'success': False,
            'error': 'Deck name is required'
        }), 400

    # Save the file to a temporary location
    _, file_extension = os.path.splitext(file.filename)
    file_extension = file_extension.lower()

    try:
        # Create a deck
        deck_id = srs_service.create_custom_deck(user_id, deck_name)

        imported_count = 0
        error_count = 0

        # Process the file based on its type
        if file_extension in ['.csv', '.txt']:
            # Handle CSV/TXT file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file.save(temp_file.name)

                try:
                    # Read the file
                    with open(temp_file.name, 'r', encoding='utf-8') as f:
                        # For CSV, parse with csv module
                        if file_extension == '.csv':
                            reader = csv.reader(f)
                            rows = list(reader)
                        # For TXT, each line is a word
                        else:
                            rows = [[line.strip()] for line in f if line.strip()]

                    # Process rows
                    for row in rows:
                        if len(row) > 0 and row[0].strip():
                            try:
                                # Create word in the database
                                word_data = {
                                    'english_word': row[0].strip(),
                                    'russian_word': row[1].strip() if len(row) > 1 else None,
                                    'status': 0  # New word
                                }

                                word_id = None

                                # Check if word already exists
                                from src.db.models import Word
                                with sqlite3.connect(DB_FILE) as conn:
                                    conn.row_factory = sqlite3.Row
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "SELECT id FROM collection_words WHERE english_word = ?",
                                        (word_data['english_word'],)
                                    )
                                    result = cursor.fetchone()

                                    if result:
                                        word_id = result['id']
                                    else:
                                        # Insert new word
                                        cursor.execute(
                                            """
                                            INSERT INTO collection_words (
                                                english_word, russian_word, status, created_at, updated_at
                                            ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                            """,
                                            (
                                                word_data['english_word'],
                                                word_data['russian_word'],
                                                word_data['status']
                                            )
                                        )
                                        conn.commit()
                                        word_id = cursor.lastrowid

                                # Add word to deck
                                if word_id:
                                    srs_service.add_word_to_deck(user_id, word_id, deck_id)
                                    imported_count += 1
                            except Exception as e:
                                logger.error(f"Error processing row {row}: {e}")
                                error_count += 1

                finally:
                    # Delete the temporary file
                    os.unlink(temp_file.name)

        elif file_extension == '.apkg':
            # Handle Anki file (simplified example)
            # In a real implementation, you would need a library to parse Anki packages
            return jsonify({
                'success': False,
                'error': 'Anki import is not yet implemented'
            }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'Unsupported file format'
            }), 400

        return jsonify({
            'success': True,
            'deck_id': deck_id,
            'imported_count': imported_count,
            'error_count': error_count
        })

    except Exception as e:
        logger.error(f"Error importing deck: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/import/words_list', methods=['POST'])
@login_required
def api_import_words_list():
    """API: Import deck from list of words."""
    user_id = session['user_id']
    data = request.json

    deck_name = data.get('deck_name', '')
    words = data.get('words', [])

    if not deck_name:
        return jsonify({
            'success': False,
            'error': 'Deck name is required'
        }), 400

    if not words:
        return jsonify({
            'success': False,
            'error': 'Word list is empty'
        }), 400

    try:
        # Create a deck
        deck_id = srs_service.create_custom_deck(user_id, deck_name)

        imported_count = 0
        error_count = 0

        # Process words
        for word_text in words:
            word_text = word_text.strip()
            if word_text:
                try:
                    # Create word in the database
                    word_data = {
                        'english_word': word_text,
                        'russian_word': None,
                        'status': 0  # New word
                    }

                    word_id = None

                    # Check if word already exists
                    from src.db.models import Word
                    with sqlite3.connect(DB_FILE) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT id FROM collection_words WHERE english_word = ?",
                            (word_data['english_word'],)
                        )
                        result = cursor.fetchone()

                        if result:
                            word_id = result['id']
                        else:
                            # Insert new word
                            cursor.execute(
                                """
                                INSERT INTO collection_words (
                                    english_word, russian_word, status, created_at, updated_at
                                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """,
                                (
                                    word_data['english_word'],
                                    word_data['russian_word'],
                                    word_data['status']
                                )
                            )
                            conn.commit()
                            word_id = cursor.lastrowid

                    # Add word to deck
                    if word_id:
                        srs_service.add_word_to_deck(user_id, word_id, deck_id)
                        imported_count += 1
                except Exception as e:
                    logger.error(f"Error processing word {word_text}: {e}")
                    error_count += 1

        return jsonify({
            'success': True,
            'deck_id': deck_id,
            'imported_count': imported_count,
            'error_count': error_count
        })

    except Exception as e:
        logger.error(f"Error importing words: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/decks')
@login_required
def decks_list():
    """List all decks for the current user."""
    user_id = session['user_id']

    # Get decks with statistics
    decks = srs_service.get_decks_with_stats(user_id)

    # Get hierarchical structure
    decks_hierarchy = []
    deck_map = {}

    # First pass - create map
    for deck in decks:
        deck['has_children'] = False
        deck['parent_id'] = None  # Will be populated for sub-decks
        deck['is_main'] = deck['name'] == "Основная колода"
        deck_map[deck['id']] = deck

    # Second pass - identify parent-child relationships
    # For demonstration, we'll use a naming convention where a deck named "parent_child"
    # is considered a child of a deck named "parent"
    for deck in decks:
        if '_' in deck['name']:
            parent_name = deck['name'].split('_')[0]
            # Find parent deck
            for parent_deck in decks:
                if parent_deck['name'] == parent_name:
                    deck['parent_id'] = parent_deck['id']
                    parent_deck['has_children'] = True
                    break

    # Third pass - create hierarchical list
    for deck in decks:
        if deck['parent_id'] is None:
            decks_hierarchy.append(deck)

    # Get detailed user statistics
    stats = srs_service.get_detailed_user_statistics(user_id)

    # Add current date/time for template
    from datetime import datetime
    now = datetime.now()

    return render_template(
        'srs/decks_list.html',
        decks=decks,
        stats=stats,
        now=now
    )


@srs_bp.route('/decks/<int:deck_id>')
@login_required
def deck_detail(deck_id):
    """Show details of a specific deck."""
    user_id = session['user_id']
    filter_type = request.args.get('filter', None)  # Get filter parameter

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        flash('Deck not found or access denied.', 'danger')
        return redirect(url_for('srs.decks_list'))

    # Get card counts
    card_counts = srs_service.get_deck_card_counts(deck_id)

    # Get filtered cards if filter is specified
    if filter_type in ['new', 'learning', 'review']:
        cards = srs_service.get_filtered_cards(deck_id, filter_type)

        # Set filter title for UI
        filter_titles = {
            'new': "New Cards",
            'learning': "Learning Cards",
            'review': "Cards to Review"
        }
        filter_title = filter_titles.get(filter_type)
    else:
        # Get all cards in deck
        cards = srs_service.srs_repo.get_cards_by_deck(deck_id)
        filter_title = None

    # Get words for cards
    word_ids = [card.word_id for card in cards]
    words = {}

    if word_ids:
        # Build placeholders for SQL query
        placeholders = ','.join(['?'] * len(word_ids))

        # Get word data from database
        try:
            import sqlite3
            from config.settings import DB_FILE

            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(
                f"SELECT * FROM collection_words WHERE id IN ({placeholders})",
                word_ids
            )

            for row in cursor.fetchall():
                word_dict = dict(row)
                words[word_dict['id']] = word_dict

        except sqlite3.Error as e:
            logger.error(f"Database error in deck_detail: {e}")
        finally:
            conn.close()

    # Get stats
    stats = srs_service.srs_repo.get_deck_statistics(deck_id)

    # Add today's date to context
    from datetime import date
    today = date.today()

    return render_template(
        'srs/deck_detail.html',
        deck=deck,
        cards=cards,
        words=words,
        stats=stats,
        today=today,
        card_counts=card_counts,
        filter_type=filter_type,
        filter_title=filter_title
    )


@srs_bp.route('/api/decks/<int:deck_id>/card_counts')
@login_required
def api_get_card_counts(deck_id):
    """API: Get card counts by category for a deck."""
    user_id = session['user_id']

    # Get deck (to check ownership)
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    # Get card counts
    card_counts = srs_service.get_deck_card_counts(deck_id)

    return jsonify({
        'success': True,
        'counts': card_counts
    })


@srs_bp.route('/decks/create', methods=['GET', 'POST'])
@login_required
def create_deck():
    """Create a new deck."""
    user_id = session['user_id']

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')

        if not name:
            flash('Deck name is required.', 'danger')
        else:
            try:
                deck_id = srs_service.create_custom_deck(user_id, name, description)
                flash(f'Deck "{name}" created successfully.', 'success')
                return redirect(url_for('srs.deck_detail', deck_id=deck_id))
            except Exception as e:
                logger.error(f"Error creating deck: {e}")
                flash(f'Error creating deck: {str(e)}', 'danger')

    return render_template('srs/create_deck.html')


@srs_bp.route('/review/data/<string:session_id>')
@login_required
def review_data(session_id):
    """Get review session data."""
    if 'review_session_data' not in session:
        return jsonify({'error': 'No active review session'}), 404

    stored_data = session.get('review_session_data', {})
    if session_id != stored_data.get('session_id'):
        return jsonify({'error': 'Invalid session ID'}), 403

    return jsonify(stored_data.get('cards', []))


@srs_bp.route('/review/<int:deck_id>')
@login_required
def start_review(deck_id):
    """Start a review session for a deck."""
    user_id = session['user_id']

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        flash('Deck not found or access denied.', 'danger')
        return redirect(url_for('srs.decks_list'))

    # Get cards due for review
    cards_data = srs_service.get_cards_for_review(deck_id)

    if not cards_data:
        flash('No cards due for review today!', 'info')
        return redirect(url_for('srs.deck_detail', deck_id=deck_id))

    # Process cards to ensure JSON serialization works
    simplified_cards = []
    for card in cards_data:
        simple_card = dict(card)  # Create a copy

        # Process date fields
        for date_field in ['next_review_date', 'last_review_date']:
            if date_field in simple_card and simple_card[date_field]:
                if hasattr(simple_card[date_field], 'isoformat'):
                    simple_card[date_field] = simple_card[date_field].isoformat()
                else:
                    simple_card[date_field] = str(simple_card[date_field])

        simplified_cards.append(simple_card)

    # Create session ID and store cards in session
    session_id = str(uuid.uuid4())
    session['review_session_data'] = {
        'session_id': session_id,
        'cards': simplified_cards,
        'deck_id': deck_id  # Store deck_id for refreshing due cards
    }

    # Store card count in session for progress tracking
    session['review_total'] = len(simplified_cards)
    session['review_done'] = 0

    # Add current date for comparisons
    from datetime import date
    today = date.today().isoformat()

    # Convert deck to dict if needed
    deck_dict = deck.to_dict() if hasattr(deck, 'to_dict') else {
        'id': deck_id,
        'name': getattr(deck, 'name', 'Deck')
    }

    return render_template(
        'srs/review_session.html',
        deck=deck_dict,
        session_id=session_id,
        today=today
    )


@srs_bp.route('/api/review/refresh-due/<string:session_id>')
@login_required
def api_refresh_due_cards(session_id):
    """API: Refresh due cards for an active review session."""
    if 'review_session_data' not in session:
        return jsonify({'success': False, 'error': 'No active review session'}), 404

    stored_data = session.get('review_session_data', {})
    if session_id != stored_data.get('session_id'):
        return jsonify({'success': False, 'error': 'Invalid session ID'}), 403

    deck_id = stored_data.get('deck_id')
    if not deck_id:
        return jsonify({'success': False, 'error': 'No deck ID associated with session'}), 400

    # Get fresh list of due cards
    cards_data = srs_service.get_cards_for_review(deck_id)

    # Process cards to ensure JSON serialization works
    simplified_cards = []
    for card in cards_data:
        simple_card = dict(card)  # Create a copy

        # Process date fields
        for date_field in ['next_review_date', 'last_review_date']:
            if date_field in simple_card and simple_card[date_field]:
                if hasattr(simple_card[date_field], 'isoformat'):
                    simple_card[date_field] = simple_card[date_field].isoformat()
                else:
                    simple_card[date_field] = str(simple_card[date_field])

        simplified_cards.append(simple_card)

    # Get IDs of already reviewed cards in this session
    already_reviewed_ids = set()
    if 'reviewed_card_ids' in session:
        already_reviewed_ids = set(session['reviewed_card_ids'])

    # Filter out cards that have already been reviewed in this session
    new_due_cards = [card for card in simplified_cards if card['id'] not in already_reviewed_ids]

    return jsonify({
        'success': True,
        'new_due_cards': new_due_cards
    })


@srs_bp.route('/statistics')
@login_required
def statistics():
    """Show learning statistics."""
    user_id = session['user_id']

    # Get user statistics
    stats = srs_service.get_user_statistics(user_id)

    return render_template(
        'srs/statistics.html',
        stats=stats
    )


# === API Routes ===

@srs_bp.route('/api/decks', methods=['GET'])
@login_required
def api_get_decks():
    """API: Get all decks for the current user."""
    user_id = session['user_id']

    try:
        # SIMPLIFIED VERSION: Direct database access to avoid potential issues with service layer
        try:
            import sqlite3
            from config.settings import DB_FILE

            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Simple query to get deck data
            cursor.execute("""
                SELECT d.id, d.name, d.description, 
                       COUNT(dc.id) as total_cards 
                FROM deck d
                LEFT JOIN deck_card dc ON d.id = dc.deck_id
                WHERE d.user_id = ?
                GROUP BY d.id
                ORDER BY d.name
            """, (user_id,))

            # Convert to simple dict to avoid serialization issues
            decks = []
            for row in cursor.fetchall():
                decks.append({
                    'id': row['id'],
                    'name': row['name'],
                    'description': row['description'],
                    'total_cards': row['total_cards']
                })

            conn.close()

            return jsonify({
                'success': True,
                'decks': decks
            })

        except sqlite3.Error as db_error:
            logger.error(f"Database error in api_get_decks: {db_error}")
            raise Exception(f"Database error: {str(db_error)}")

    except Exception as e:
        logger.error(f"Error in api_get_decks: {e}")
        import traceback
        logger.error(traceback.format_exc())

        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'An error occurred fetching decks'
        }), 500


@srs_bp.route('/api/decks/<int:deck_id>', methods=['PUT'])
@login_required
def api_update_deck(deck_id):
    """API: Update a deck."""
    user_id = session['user_id']
    data = request.json

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    name = data.get('name')
    description = data.get('description')

    try:
        updated = srs_service.srs_repo.update_deck(
            deck_id=deck_id,
            name=name,
            description=description
        )

        if updated:
            deck = srs_service.srs_repo.get_deck_by_id(deck_id)
            return jsonify({
                'success': True,
                'deck': deck.to_dict() if deck else {'id': deck_id}
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Deck not updated'
            }), 500
    except Exception as e:
        logger.error(f"Error updating deck: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/decks/<int:deck_id>', methods=['DELETE'])
@login_required
def api_delete_deck(deck_id):
    """API: Delete a deck."""
    user_id = session['user_id']

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    # Don't allow deleting the main deck
    if deck.name == "Основная колода":
        return jsonify({
            'success': False,
            'error': 'Cannot delete the main deck'
        }), 403

    try:
        deleted = srs_service.srs_repo.delete_deck(deck_id)

        return jsonify({
            'success': deleted
        })
    except Exception as e:
        logger.error(f"Error deleting deck: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/decks/<int:deck_id>/cards', methods=['GET'])
@login_required
def api_get_cards(deck_id):
    """API: Get all cards in a deck."""
    user_id = session['user_id']

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    # Get cards
    cards = srs_service.srs_repo.get_cards_by_deck(deck_id)

    return jsonify({
        'success': True,
        'cards': [card.to_dict() for card in cards]
    })


@srs_bp.route('/api/decks/<int:deck_id>/cards', methods=['POST'])
@login_required
def api_add_card(deck_id):
    """API: Add a word to a deck."""
    user_id = session['user_id']
    data = request.json

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    word_id = data.get('word_id')

    if not word_id:
        return jsonify({
            'success': False,
            'error': 'Word ID is required'
        }), 400

    try:
        card_id = srs_service.add_word_to_deck(user_id, word_id, deck_id)
        card = srs_service.srs_repo.get_card_by_id(card_id)

        return jsonify({
            'success': True,
            'card': card.to_dict() if card else {'id': card_id}
        })
    except Exception as e:
        logger.error(f"Error adding card: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/cards/<int:card_id>', methods=['DELETE'])
@login_required
def api_delete_card(card_id):
    """API: Delete a card from a deck."""
    user_id = session['user_id']

    # Get card
    card = srs_service.srs_repo.get_card_by_id(card_id)
    if not card:
        return jsonify({
            'success': False,
            'error': 'Card not found'
        }), 404

    # Get deck (to check ownership)
    deck = srs_service.srs_repo.get_deck_by_id(card.deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Access denied'
        }), 403

    try:
        deleted = srs_service.remove_word_from_deck(card_id)

        return jsonify({
            'success': deleted
        })
    except Exception as e:
        logger.error(f"Error deleting card: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/cards/<int:card_id>/move', methods=['POST'])
@login_required
def api_move_card(card_id):
    """API: Move a card to another deck."""
    user_id = session['user_id']
    data = request.json

    # Get card
    card = srs_service.srs_repo.get_card_by_id(card_id)
    if not card:
        return jsonify({
            'success': False,
            'error': 'Card not found'
        }), 404

    # Get source deck (to check ownership)
    source_deck = srs_service.srs_repo.get_deck_by_id(card.deck_id)
    if not source_deck or source_deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Access denied'
        }), 403

    # Get target deck
    target_deck_id = data.get('deck_id')
    if not target_deck_id:
        return jsonify({
            'success': False,
            'error': 'Target deck ID is required'
        }), 400

    target_deck = srs_service.srs_repo.get_deck_by_id(target_deck_id)
    if not target_deck or target_deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Target deck not found or access denied'
        }), 404

    try:
        moved = srs_service.move_word_to_deck(card_id, target_deck_id)

        return jsonify({
            'success': moved
        })
    except Exception as e:
        logger.error(f"Error moving card: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/review/<int:card_id>', methods=['POST'])
@login_required
def api_review_card(card_id):
    """API: Process a card review."""
    user_id = session['user_id']
    data = request.json

    # Get card
    card = srs_service.srs_repo.get_card_by_id(card_id)
    if not card:
        return jsonify({
            'success': False,
            'error': 'Card not found'
        }), 404

    # Get deck (to check ownership)
    deck = srs_service.srs_repo.get_deck_by_id(card.deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Access denied'
        }), 403

    difficulty = data.get('difficulty')
    if difficulty not in ('again', 'hard', 'good', 'easy'):
        return jsonify({
            'success': False,
            'error': 'Invalid difficulty level'
        }), 400

    # Get any additional data
    time_seconds = data.get('time_seconds')  # Time spent on this card in seconds

    try:
        updated_card = srs_service.process_review(card_id, user_id, difficulty)

        # Update review progress in session
        if 'review_done' in session:
            session['review_done'] = session.get('review_done', 0) + 1

        # Track reviewed card IDs to avoid duplicate reviews in the same session
        if 'reviewed_card_ids' not in session:
            session['reviewed_card_ids'] = []

        # Only add to the reviewed list if it's not "again" (as we want to review it again)
        if difficulty != 'again':
            if card_id not in session['reviewed_card_ids']:
                session['reviewed_card_ids'].append(card_id)

        # Record in review session log and card review history
        try:
            import sqlite3
            from config.settings import DB_FILE
            from datetime import date, datetime
            from src.srs.models import ReviewSessionLog, CardReviewHistory

            # 1. Update review_session_log
            try:
                conn = sqlite3.connect(DB_FILE)
                # Ensure the review_session_log table exists
                ReviewSessionLog.ensure_table_exists(conn)

                # Get or create today's session log
                today = date.today()
                session_log = ReviewSessionLog.get_or_create(conn, user_id, today)

                # Update the log with this review
                time_seconds_value = int(time_seconds) if time_seconds is not None else None
                session_log.increment_reviewed(1, time_seconds_value)
                session_log.save(conn)

            except Exception as log_error:
                logger.error(f"Error updating review_session_log: {log_error}")

            # 2. Record in card_review_history
            try:
                # Ensure card_review_history table exists
                CardReviewHistory.ensure_table_exists(conn)

                # Add the review record
                CardReviewHistory.add_review(
                    conn, card_id, user_id, difficulty, time_seconds
                )

            except Exception as history_error:
                logger.error(f"Error recording in card_review_history: {history_error}")

            # Close connection
            conn.close()

        except Exception as db_error:
            logger.error(f"Database error logging review: {db_error}")

        return jsonify({
            'success': True,
            'card': updated_card
        })
    except Exception as e:
        logger.error(f"Error processing review: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/decks/<int:deck_id>/due', methods=['GET'])
@login_required
def api_get_due_cards(deck_id):
    """API: Get cards due for review today."""
    user_id = session['user_id']

    # Get deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    try:
        cards = srs_service.get_cards_for_review(deck_id)

        return jsonify({
            'success': True,
            'cards': cards
        })
    except Exception as e:
        logger.error(f"Error getting due cards: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Добавьте эти новые эндпоинты в routes.py, в секцию API Routes

@srs_bp.route('/api/import/deck', methods=['POST'])
@login_required
def api_import_deck():
    """API: Import words as a new deck."""
    user_id = session['user_id']
    data = request.json

    deck_name = data.get('deckName')
    description = data.get('description', '')
    word_ids = data.get('wordIds', [])

    if not word_ids:
        return jsonify({
            'success': False,
            'error': 'No words selected for import'
        }), 400

    if not deck_name:
        return jsonify({
            'success': False,
            'error': 'Deck name is required'
        }), 400

    try:
        # Create new deck
        deck_id = srs_service.create_custom_deck(user_id, deck_name, description)

        # Add words to deck
        added_count = 0
        for word_id in word_ids:
            try:
                card_id = srs_service.add_word_to_deck(user_id, word_id, deck_id)
                if card_id:
                    added_count += 1
            except Exception as e:
                logger.warning(f"Failed to add word {word_id} to deck: {e}")

        return jsonify({
            'success': True,
            'deckId': deck_id,
            'addedCount': added_count,
            'totalCount': len(word_ids)
        })
    except Exception as e:
        logger.error(f"Error importing deck: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/import/words', methods=['POST'])
@login_required
def api_import_words():
    """API: Import words into an existing deck."""
    user_id = session['user_id']
    data = request.json

    deck_id = data.get('deckId')
    word_ids = data.get('wordIds', [])

    if not deck_id:
        return jsonify({
            'success': False,
            'error': 'Deck ID is required'
        }), 400

    if not word_ids:
        return jsonify({
            'success': False,
            'error': 'No words selected for import'
        }), 400

    # Check if user owns the deck
    deck = srs_service.srs_repo.get_deck_by_id(deck_id)
    if not deck or deck.user_id != user_id:
        return jsonify({
            'success': False,
            'error': 'Deck not found or access denied'
        }), 404

    try:
        # Add words to deck
        added_count = 0
        skipped_count = 0

        for word_id in word_ids:
            try:
                # Check if word already exists in deck
                existing_card = srs_service.srs_repo.get_card_by_deck_and_word(deck_id, word_id)
                if existing_card:
                    skipped_count += 1
                    continue

                card_id = srs_service.add_word_to_deck(user_id, word_id, deck_id)
                if card_id:
                    added_count += 1
            except Exception as e:
                logger.warning(f"Failed to add word {word_id} to deck: {e}")

        return jsonify({
            'success': True,
            'deckId': deck_id,
            'addedCount': added_count,
            'skippedCount': skipped_count,
            'totalCount': len(word_ids)
        })
    except Exception as e:
        logger.error(f"Error importing words to deck: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/sync/word_status', methods=['POST'])
@login_required
def api_sync_word_status():
    """API: Synchronize word status with deck card status"""
    user_id = session['user_id']
    data = request.json or {}
    selected_word_ids = data.get('wordIds', [])

    try:
        # Connect to database
        import sqlite3
        from config.settings import DB_FILE
        from src.db.models import Word  # Импортируем класс Word для доступа к константам статусов

        logger.info(f"Starting word status sync for user {user_id}")
        if selected_word_ids:
            logger.info(f"Syncing status for {len(selected_word_ids)} selected words")

        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all deck IDs for the user
        cursor.execute(
            "SELECT id FROM deck WHERE user_id = ?",
            (user_id,)
        )
        user_deck_ids = [row['id'] for row in cursor.fetchall()]

        if not user_deck_ids:
            return jsonify({
                'success': True,
                'updated_count': 0,
                'message': 'No decks found for the user'
            })

        # Format deck IDs for SQL query
        deck_id_placeholders = ','.join(['?' for _ in user_deck_ids])

        # Find words to update - either selected words or all words in decks
        word_ids_to_update = []

        if selected_word_ids:
            # If specific words are selected, check which of them are in decks and have status=0
            selected_id_placeholders = ','.join(['?' for _ in selected_word_ids])

            # Check in collection_words table for learning_status = 0 (New)
            cursor.execute(
                f"""
                SELECT DISTINCT w.id 
                FROM collection_words w
                JOIN deck_card dc ON w.id = dc.word_id
                WHERE dc.deck_id IN ({deck_id_placeholders})
                AND w.id IN ({selected_id_placeholders})
                AND w.learning_status = 0
                """,
                user_deck_ids + selected_word_ids
            )

            # Add words with global learning_status = 0 (New)
            global_new_words = [row[0] for row in cursor.fetchall()]
            word_ids_to_update.extend(global_new_words)

            # Also check user_word_status table (if it exists) for user-specific status
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
            if cursor.fetchone():
                cursor.execute(
                    f"""
                    SELECT DISTINCT uws.word_id 
                    FROM user_word_status uws
                    JOIN deck_card dc ON uws.word_id = dc.word_id
                    WHERE dc.deck_id IN ({deck_id_placeholders})
                    AND uws.word_id IN ({selected_id_placeholders})
                    AND uws.user_id = ?
                    AND uws.status = 0
                    AND uws.word_id NOT IN ({','.join(['?' for _ in global_new_words]) if global_new_words else 'SELECT -1'})
                    """,
                    user_deck_ids + selected_word_ids + [user_id] + global_new_words
                )

                # Add words with user-specific status = 0 (New)
                user_new_words = [row[0] for row in cursor.fetchall()]
                word_ids_to_update.extend(user_new_words)

                # Also find words that have no status entry in user_word_status but are in decks
                cursor.execute(
                    f"""
                    SELECT DISTINCT dc.word_id 
                    FROM deck_card dc
                    WHERE dc.deck_id IN ({deck_id_placeholders})
                    AND dc.word_id IN ({selected_id_placeholders})
                    AND dc.word_id NOT IN (
                        SELECT word_id FROM user_word_status 
                        WHERE user_id = ? AND word_id IN ({selected_id_placeholders})
                    )
                    AND dc.word_id NOT IN ({','.join(['?' for _ in word_ids_to_update]) if word_ids_to_update else 'SELECT -1'})
                    """,
                    user_deck_ids + selected_word_ids + [user_id] + selected_word_ids + word_ids_to_update
                )

                # Add words that have no user status entry
                no_status_words = [row[0] for row in cursor.fetchall()]
                word_ids_to_update.extend(no_status_words)
        else:
            # Find all words in user's decks that have learning_status = 0 (New) in collection_words
            cursor.execute(
                f"""
                SELECT DISTINCT dc.word_id 
                FROM deck_card dc
                JOIN collection_words cw ON dc.word_id = cw.id
                WHERE dc.deck_id IN ({deck_id_placeholders})
                AND cw.learning_status = 0
                """,
                user_deck_ids
            )

            global_new_words = [row[0] for row in cursor.fetchall()]
            word_ids_to_update.extend(global_new_words)

            # Also check user_word_status table (if it exists)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
            if cursor.fetchone():
                cursor.execute(
                    f"""
                    SELECT DISTINCT uws.word_id 
                    FROM user_word_status uws
                    JOIN deck_card dc ON uws.word_id = dc.word_id
                    WHERE dc.deck_id IN ({deck_id_placeholders})
                    AND uws.user_id = ?
                    AND uws.status = 0
                    AND uws.word_id NOT IN ({','.join(['?' for _ in global_new_words]) if global_new_words else 'SELECT -1'})
                    """,
                    user_deck_ids + [user_id] + global_new_words
                )

                user_new_words = [row[0] for row in cursor.fetchall()]
                word_ids_to_update.extend(user_new_words)

                # Find words that have no status entry
                cursor.execute(
                    f"""
                    SELECT DISTINCT dc.word_id 
                    FROM deck_card dc
                    WHERE dc.deck_id IN ({deck_id_placeholders})
                    AND dc.word_id NOT IN (
                        SELECT word_id FROM user_word_status WHERE user_id = ?
                    )
                    AND dc.word_id NOT IN ({','.join(['?' for _ in word_ids_to_update]) if word_ids_to_update else 'SELECT -1'})
                    """,
                    user_deck_ids + [user_id] + word_ids_to_update
                )

                no_status_words = [row[0] for row in cursor.fetchall()]
                word_ids_to_update.extend(no_status_words)

        logger.info(f"Found {len(word_ids_to_update)} words to update status")

        if not word_ids_to_update:
            return jsonify({
                'success': True,
                'updated_count': 0,
                'message': 'No words need status update'
            })

        # If selected words are provided but none of them need update, check if they're in decks
        if selected_word_ids and not word_ids_to_update:
            selected_id_placeholders = ','.join(['?' for _ in selected_word_ids])

            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT w.id) 
                FROM collection_words w
                JOIN deck_card dc ON w.id = dc.word_id
                WHERE dc.deck_id IN ({deck_id_placeholders})
                AND w.id IN ({selected_id_placeholders})
                AND w.learning_status != 0
                """,
                user_deck_ids + selected_word_ids
            )

            already_active_global = cursor.fetchone()[0]

            # Check if any selected words have non-zero user-specific status
            already_active_user = 0
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
            if cursor.fetchone():
                cursor.execute(
                    f"""
                    SELECT COUNT(DISTINCT uws.word_id) 
                    FROM user_word_status uws
                    JOIN deck_card dc ON uws.word_id = dc.word_id
                    WHERE dc.deck_id IN ({deck_id_placeholders})
                    AND uws.word_id IN ({selected_id_placeholders})
                    AND uws.user_id = ?
                    AND uws.status != 0
                    """,
                    user_deck_ids + selected_word_ids + [user_id]
                )
                already_active_user = cursor.fetchone()[0]

            if already_active_global > 0 or already_active_user > 0:
                return jsonify({
                    'success': True,
                    'updated_count': 0,
                    'message': f'Selected words are already properly marked (not New status)'
                })

            # If no selected words are in decks at all, inform the user
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT w.id) 
                FROM collection_words w
                JOIN deck_card dc ON w.id = dc.word_id
                WHERE dc.deck_id IN ({deck_id_placeholders})
                AND w.id IN ({selected_id_placeholders})
                """,
                user_deck_ids + selected_word_ids
            )

            in_decks_count = cursor.fetchone()[0]
            if in_decks_count == 0:
                return jsonify({
                    'success': True,
                    'updated_count': 0,
                    'message': f'Selected words are not in any of your decks'
                })

        # Update the word_ids_to_update in both tables
        updated_count = 0

        # 1. Update global learning_status in collection_words
        if word_ids_to_update:
            word_id_placeholders = ','.join(['?' for _ in word_ids_to_update])

            cursor.execute(
                f"""
                UPDATE collection_words
                SET learning_status = 3  -- Word.STATUS_ACTIVE
                WHERE id IN ({word_id_placeholders})
                AND learning_status = 0  -- Only update NEW words
                """,
                word_ids_to_update
            )

            global_updated = cursor.rowcount
            logger.info(f"Updated {global_updated} words in collection_words table")
            updated_count += global_updated

        # 2. Update or insert into user_word_status
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
        if cursor.fetchone() and word_ids_to_update:
            # For words with existing user status
            cursor.execute(
                f"""
                UPDATE user_word_status
                SET status = 3,  -- Word.STATUS_ACTIVE
                    last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ?
                AND word_id IN ({word_id_placeholders})
                AND status = 0  -- Only update NEW words
                """,
                [user_id] + word_ids_to_update
            )

            user_updated = cursor.rowcount
            logger.info(f"Updated {user_updated} words in user_word_status table")

            # For words without existing user status entry
            cursor.execute(
                f"""
                INSERT INTO user_word_status (user_id, word_id, status, last_updated)
                SELECT 
                    ?,
                    w.id,
                    3,  -- Word.STATUS_ACTIVE
                    CURRENT_TIMESTAMP
                FROM collection_words w
                WHERE w.id IN ({word_id_placeholders})
                AND NOT EXISTS (
                    SELECT 1 FROM user_word_status 
                    WHERE user_id = ? AND word_id = w.id
                )
                """,
                [user_id] + word_ids_to_update + [user_id]
            )

            user_inserted = cursor.rowcount
            logger.info(f"Inserted {user_inserted} new entries in user_word_status table")

        conn.commit()

        message = f'Successfully updated {updated_count} words to Active status'
        if selected_word_ids:
            message = f'Successfully updated {updated_count} of {len(selected_word_ids)} selected words'

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'message': message
        })

    except Exception as e:
        # Log full exception details
        import traceback
        logger.error(f"Unexpected error syncing word status: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }), 500
    finally:
        if 'conn' in locals():
            conn.close()


@srs_bp.route('/api/test', methods=['GET'])
@login_required
def api_test():
    """API: Simple test endpoint to verify API functionality"""
    user_id = session['user_id']

    # Get basic user info
    try:
        decks_count = len(srs_service.get_decks_with_stats(user_id))

        return jsonify({
            'success': True,
            'user_id': user_id,
            'decks_count': decks_count,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Test endpoint error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/statistics', methods=['GET'])
@login_required
def api_get_statistics():
    """API: Get user statistics."""
    user_id = session['user_id']

    try:
        stats = srs_service.get_user_statistics(user_id)

        return jsonify({
            'success': True,
            'statistics': stats
        })
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@srs_bp.route('/api/activity/<int:year>')
@login_required
def api_get_activity(year):
    """API: Get user activity data for a specific year."""
    user_id = session['user_id']
    logger.info(f"Getting activity data for user {user_id}, year {year}")

    try:
        import sqlite3
        from config.settings import DB_FILE
        from datetime import datetime, date, timedelta

        # Create empty response object - key is date string, value is activity data
        activity_data = {}

        # Calculate date range for the year - ALWAYS include full year for scheduled cards
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)  # Always get full year for scheduled cards

        # For review history, limit to current date
        current_date = datetime.now().date()
        review_end_date = min(end_date, current_date)

        logger.info(f"Date ranges: full year {start_date} to {end_date}, reviews up to {review_end_date}")
        print(f"Date ranges: full year {start_date} to {end_date}, reviews up to {review_end_date}")

        # Create connection
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Debug: log exact SQL query and data to debug format issues
        def debug_query(query, params):
            query_with_params = query
            for param in params:
                query_with_params = query_with_params.replace('?', repr(param), 1)
            logger.debug(f"Executing query: {query_with_params}")

        # Check if user has decks
        cursor.execute("SELECT COUNT(*) as count FROM deck WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        has_decks = result['count'] > 0

        # If user has no decks, return empty data
        if not has_decks:
            logger.info(f"User {user_id} has no decks, returning empty activity data")
            return jsonify({})

        # 1. Get completed reviews from review_session_log
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_session_log'")
        if cursor.fetchone():
            # Table exists
            logger.info("Fetching data from review_session_log table")

            query = """
            SELECT 
                session_date, 
                SUM(cards_reviewed) as reviewed,
                SUM(duration_seconds) / 60 as minutes
            FROM review_session_log
            WHERE user_id = ? AND session_date BETWEEN ? AND ?
            GROUP BY session_date
            """

            debug_query(query, (user_id, start_date.isoformat(), review_end_date.isoformat()))

            cursor.execute(
                query,
                (user_id, start_date.isoformat(), review_end_date.isoformat())
            )

            for row in cursor.fetchall():
                date_str = row['session_date']
                reviewed = row['reviewed'] or 0
                minutes = int(row['minutes'] or 0) if row['minutes'] is not None else 0

                activity_data[date_str] = {
                    'reviewed': reviewed,
                    'minutes': minutes,
                    'scheduled': 0,  # Will be updated if there are scheduled cards
                    'status': 'completed'
                }

            logger.info(f"Found {len(activity_data)} days with review activity")

        # 2. Get scheduled cards from deck_card - include FUTURE dates
        cursor.execute("PRAGMA table_info(deck_card)")
        columns = [row['name'] for row in cursor.fetchall()]

        if 'next_review_date' in columns:
            logger.info("Fetching scheduled cards from deck_card table")
            print(f"Looking for scheduled cards between {start_date} and {end_date}")
            # Query for scheduled cards - NOTE: Using full year range, not just up to current date

            query = """
            SELECT 
                next_review_date, 
                COUNT(*) as scheduled_count
            FROM deck_card dc
            JOIN deck d ON dc.deck_id = d.id
            WHERE d.user_id = ? 
                AND next_review_date BETWEEN ? AND ?
            GROUP BY next_review_date
            """

            debug_query(query, (user_id, start_date.isoformat(), end_date.isoformat()))

            cursor.execute(
                query,
                (user_id, start_date.isoformat(), end_date.isoformat())
            )

            scheduled_dates_count = 0

            for row in cursor.fetchall():
                if not row['next_review_date']:
                    continue

                date_str = row['next_review_date']
                scheduled_count = row['scheduled_count'] or 0

                scheduled_dates_count += 1
                print(f"Found scheduled date: {date_str} with {scheduled_count} cards")
                logger.debug(f"Found {scheduled_count} scheduled cards for {date_str}")

                if date_str in activity_data:
                    # Update existing entry
                    activity_data[date_str]['scheduled'] = scheduled_count

                    # If this is only a scheduled date, update status
                    if activity_data[date_str]['reviewed'] == 0:
                        activity_data[date_str]['status'] = 'scheduled'
                else:
                    # Create new entry for scheduled cards
                    activity_data[date_str] = {
                        'reviewed': 0,
                        'minutes': 0,
                        'scheduled': scheduled_count,
                        'status': 'scheduled'
                    }

            logger.info(f"Added {scheduled_dates_count} dates with scheduled cards to activity data")

            # Debug: Log all scheduled dates
            for date_str, data in activity_data.items():
                if data.get('scheduled', 0) > 0:
                    logger.debug(f"Date {date_str} has {data['scheduled']} scheduled cards")

        # 3. Fill in dates with zero activity for complete calendar
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.isoformat()
            if date_str not in activity_data:
                activity_data[date_str] = {
                    'reviewed': 0,
                    'minutes': 0,
                    'scheduled': 0,
                    'status': 'none'
                }
            current_date += timedelta(days=1)

        # 4. Log and return data
        logger.info(f"Returning activity data for {len(activity_data)} days")

        return jsonify(activity_data)

    except Exception as e:
        # Log full exception details
        import traceback
        logger.error(f"Error in activity API: {e}")
        logger.error(traceback.format_exc())

        # Return empty data on error
        return jsonify({})


@srs_bp.route('/api/activity/clear', methods=['POST'])
@login_required
def api_clear_activity():
    """API: Clear user activity history."""
    user_id = session['user_id']

    try:
        import sqlite3
        from config.settings import DB_FILE

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Проверяем, существует ли таблица review_session_log
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_session_log'")
        table_exists = cursor.fetchone() is not None

        if table_exists:
            # Удаляем все записи для данного пользователя
            cursor.execute(
                "DELETE FROM review_session_log WHERE user_id = ?",
                (user_id,)
            )
            deleted_count = cursor.rowcount
            conn.commit()

            logger.info(f"Cleared {deleted_count} activity records for user {user_id}")

            return jsonify({
                'success': True,
                'message': f'Cleared {deleted_count} activity records'
            })
        else:
            return jsonify({
                'success': True,
                'message': 'No activity records to clear (table does not exist)'
            })

    except Exception as e:
        logger.error(f"Error clearing activity data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if 'conn' in locals():
            conn.close()


"""
Новый API эндпоинт для получения актуальных статусов слов
Добавьте этот код в routes.py или ваш файл маршрутов API
"""


@srs_bp.route('/api/words/statuses', methods=['POST'])
@login_required
def api_get_word_statuses():
    """API: Get current statuses for specific words"""
    user_id = session['user_id']
    data = request.json or {}
    word_ids = data.get('wordIds', [])

    if not word_ids:
        return jsonify({
            'success': False,
            'error': 'No word IDs provided'
        }), 400

    try:
        import sqlite3
        from config.settings import DB_FILE
        from src.db.models import Word

        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Формируем плейсхолдеры для SQL запроса
        placeholders = ','.join(['?' for _ in word_ids])

        # Общая статистика по статусам слов
        cursor.execute(
            """
            SELECT learning_status, COUNT(*) as count
            FROM collection_words
            GROUP BY learning_status
            """,
        )

        status_counts = {
            Word.STATUS_NEW: 0,
            Word.STATUS_STUDYING: 0,
            Word.STATUS_STUDIED: 0,
        }

        for row in cursor.fetchall():
            status, count = row
            status_counts[status] = count

        # Проверяем, есть ли таблица user_word_status
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_word_status'")
        has_user_statuses = cursor.fetchone() is not None

        # Получаем статусы запрошенных слов
        statuses = {}

        # Получаем глобальные статусы из collection_words
        cursor.execute(
            f"""
            SELECT id, english_word, learning_status
            FROM collection_words
            WHERE id IN ({placeholders})
            """,
            word_ids
        )

        for row in cursor.fetchall():
            word_id = row['id']
            status = row['learning_status']

            # Преобразуем статус в понятную метку
            status_label = Word.STATUS_LABELS.get(status, "Неизвестный статус")

            statuses[word_id] = {
                'word_id': word_id,
                'english_word': row['english_word'],
                'status': status,
                'label': status_label
            }

        # Если есть пользовательские статусы, учитываем их
        if has_user_statuses:
            cursor.execute(
                f"""
                SELECT word_id, status
                FROM user_word_status
                WHERE user_id = ? AND word_id IN ({placeholders})
                """,
                [user_id] + word_ids
            )

            for row in cursor.fetchall():
                word_id = row['word_id']
                status = row['status']

                # Если слово уже было найдено в глобальной таблице
                if word_id in statuses:
                    # Пользовательский статус имеет приоритет над глобальным
                    status_label = Word.STATUS_LABELS.get(status, "Неизвестный статус")
                    statuses[word_id]['status'] = status
                    statuses[word_id]['label'] = status_label

        return jsonify({
            'success': True,
            'statuses': statuses,
            'counts': status_counts
        })

    except Exception as e:
        import traceback
        logger.error(f"Error getting word statuses: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if 'conn' in locals():
            conn.close()