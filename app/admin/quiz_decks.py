"""
Quiz Decks management routes for admin panel
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.admin.main_routes import admin
from app.study.models import QuizDeck, QuizDeckWord, QuizResult
from app.utils.db import db
from app.words.models import CollectionWords


@admin.route('/quiz-decks')
@login_required
def quiz_decks_list():
    """List all quiz decks"""
    if not current_user.is_admin:
        flash('У вас нет прав для доступа к этой странице', 'danger')
        return redirect(url_for('main.index'))

    page = request.args.get('page', 1, type=int)
    per_page = 20

    decks_query = QuizDeck.query.order_by(QuizDeck.created_at.desc())

    # Search
    search = request.args.get('search', '')
    if search:
        decks_query = decks_query.filter(
            db.or_(
                QuizDeck.title.ilike(f'%{search}%'),
                QuizDeck.description.ilike(f'%{search}%')
            )
        )

    pagination = decks_query.paginate(page=page, per_page=per_page, error_out=False)
    decks = pagination.items

    return render_template(
        'admin/quiz_decks/list.html',
        decks=decks,
        pagination=pagination,
        search=search
    )


@admin.route('/quiz-decks/create', methods=['GET', 'POST'])
@login_required
def quiz_deck_create():
    """Create new quiz deck"""
    if not current_user.is_admin:
        flash('У вас нет прав для доступа к этой странице', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        is_public = request.form.get('is_public') == 'on'

        if not title:
            flash('Название колоды обязательно', 'danger')
            return redirect(url_for('admin.quiz_deck_create'))

        deck = QuizDeck(
            title=title,
            description=description,
            user_id=current_user.id,
            is_public=is_public
        )

        if is_public:
            deck.generate_share_code()

        db.session.add(deck)
        db.session.commit()

        flash(f'Колода "{title}" успешно создана', 'success')
        return redirect(url_for('admin.quiz_deck_edit', deck_id=deck.id))

    return render_template('admin/quiz_decks/create.html')


@admin.route('/quiz-decks/<int:deck_id>')
@login_required
def quiz_deck_view(deck_id):
    """View quiz deck details"""
    if not current_user.is_admin:
        flash('У вас нет прав для доступа к этой странице', 'danger')
        return redirect(url_for('main.index'))

    deck = QuizDeck.query.get_or_404(deck_id)
    words = deck.words.order_by(QuizDeckWord.order_index).all()

    # Get statistics
    total_plays = deck.results.count()
    avg_score = db.session.query(func.avg(QuizResult.score_percentage)).filter(
        QuizResult.deck_id == deck_id
    ).scalar() or 0

    return render_template(
        'admin/quiz_decks/view.html',
        deck=deck,
        words=words,
        total_plays=total_plays,
        avg_score=round(avg_score, 1)
    )


@admin.route('/quiz-decks/<int:deck_id>/edit', methods=['GET', 'POST'])
@login_required
def quiz_deck_edit(deck_id):
    """Edit quiz deck"""
    if not current_user.is_admin:
        flash('У вас нет прав для доступа к этой странице', 'danger')
        return redirect(url_for('main.index'))

    deck = QuizDeck.query.get_or_404(deck_id)

    if request.method == 'POST':
        deck.title = request.form.get('title')
        deck.description = request.form.get('description')
        was_public = deck.is_public
        deck.is_public = request.form.get('is_public') == 'on'

        # Generate share code if making public for the first time
        if deck.is_public and not was_public and not deck.share_code:
            deck.generate_share_code()

        db.session.commit()

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({
                'success': True,
                'message': 'Колода успешно обновлена',
                'share_code': deck.share_code if deck.is_public else None,
                'share_link': url_for('study.quiz_deck_shared', code=deck.share_code, _external=True) if deck.share_code and deck.is_public else None
            })

        flash('Колода успешно обновлена', 'success')
        return redirect(url_for('admin.quiz_deck_view', deck_id=deck.id))

    words = deck.words.order_by(QuizDeckWord.order_index).all()

    return render_template(
        'admin/quiz_decks/edit.html',
        deck=deck,
        words=words
    )


@admin.route('/quiz-decks/<int:deck_id>/delete', methods=['POST'])
@login_required
def quiz_deck_delete(deck_id):
    """Delete quiz deck"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck = QuizDeck.query.get_or_404(deck_id)
    title = deck.title

    db.session.delete(deck)
    db.session.commit()

    # Check if AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({
            'success': True,
            'message': f'Колода "{title}" успешно удалена'
        })

    flash(f'Колода "{title}" успешно удалена', 'success')
    return redirect(url_for('admin.quiz_decks_list'))


@admin.route('/quiz-decks/<int:deck_id>/words/add', methods=['POST'])
@login_required
def quiz_deck_add_word(deck_id):
    """Add word to quiz deck - supports both existing words and custom translations"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck = QuizDeck.query.get_or_404(deck_id)

    word_id = request.form.get('word_id', type=int)
    custom_english = request.form.get('custom_english', '').strip()
    custom_russian = request.form.get('custom_russian', '').strip()

    # Validation
    if not custom_english or not custom_russian:
        flash('Необходимо заполнить оба поля', 'danger')
        return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))

    # Get max order index
    max_order = db.session.query(func.max(QuizDeckWord.order_index)).filter(
        QuizDeckWord.deck_id == deck_id
    ).scalar() or 0

    # If word_id provided, check if it's already in deck
    if word_id:
        existing = QuizDeckWord.query.filter_by(
            deck_id=deck_id,
            word_id=word_id
        ).first()

        if existing:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
                return jsonify({'success': False, 'message': 'Это слово уже в колоде'}), 400
            flash('Это слово уже в колоде', 'info')
            return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))

        # Add word from collection with optional custom override
        word = CollectionWords.query.get(word_id)
        if not word:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
                return jsonify({'success': False, 'message': 'Слово не найдено в базе'}), 400
            flash('Слово не найдено в базе', 'danger')
            return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))

        deck_word = QuizDeckWord(
            deck_id=deck_id,
            word_id=word_id,
            order_index=max_order + 1
        )

        # If translation differs from original, save as custom override
        if custom_english != word.english_word or custom_russian != word.russian_word:
            deck_word.custom_english = custom_english
            deck_word.custom_russian = custom_russian

        db.session.add(deck_word)
        db.session.commit()

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({
                'success': True,
                'message': 'Слово добавлено в колоду',
                'word': {
                    'id': deck_word.id,
                    'deck_id': deck_id,
                    'english': deck_word.english_word,
                    'russian': deck_word.russian_word,
                    'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None
                }
            })

        flash('Слово добавлено в колоду', 'success')

    else:
        # Add completely custom word (not in collection)
        deck_word = QuizDeckWord(
            deck_id=deck_id,
            custom_english=custom_english,
            custom_russian=custom_russian,
            order_index=max_order + 1
        )
        db.session.add(deck_word)
        db.session.commit()

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({
                'success': True,
                'message': 'Своё слово добавлено в колоду',
                'word': {
                    'id': deck_word.id,
                    'deck_id': deck_id,
                    'english': deck_word.english_word,
                    'russian': deck_word.russian_word,
                    'has_custom': True
                }
            })

        flash('Своё слово добавлено в колоду', 'success')

    return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))


@admin.route('/quiz-decks/<int:deck_id>/words/<int:word_id>/update', methods=['POST'])
@login_required
def quiz_deck_update_word(deck_id, word_id):
    """Update word in quiz deck - saves custom override for this deck"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck_word = QuizDeckWord.query.filter_by(deck_id=deck_id, id=word_id).first_or_404()

    custom_english = request.form.get('custom_english', '').strip()
    custom_russian = request.form.get('custom_russian', '').strip()

    if not custom_english or not custom_russian:
        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
            return jsonify({'success': False, 'message': 'Оба поля должны быть заполнены'}), 400
        flash('Оба поля должны быть заполнены', 'danger')
        return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))

    # Save custom override - works for both collection words and custom words
    deck_word.custom_english = custom_english
    deck_word.custom_russian = custom_russian

    db.session.commit()

    # Check if AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({
            'success': True,
            'message': 'Перевод обновлен',
            'word': {
                'id': deck_word.id,
                'english': deck_word.english_word,
                'russian': deck_word.russian_word,
                'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None
            }
        })

    flash('Перевод обновлен для этой колоды', 'success')
    return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))


@admin.route('/quiz-decks/<int:deck_id>/words/<int:word_id>/reset', methods=['POST'])
@login_required
def quiz_deck_reset_word(deck_id, word_id):
    """Reset custom override to original translation"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck_word = QuizDeckWord.query.filter_by(deck_id=deck_id, id=word_id).first_or_404()

    # Only reset if this is a word from collection (has word_id)
    if deck_word.word_id is None:
        flash('Нельзя сбросить полностью custom слово', 'warning')
        return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))

    # Clear custom overrides
    deck_word.custom_english = None
    deck_word.custom_russian = None

    db.session.commit()

    flash('Перевод сброшен к оригинальному', 'success')
    return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))


@admin.route('/quiz-decks/<int:deck_id>/words/<int:word_id>/delete', methods=['POST'])
@login_required
def quiz_deck_remove_word(deck_id, word_id):
    """Remove word from quiz deck"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck_word = QuizDeckWord.query.filter_by(deck_id=deck_id, id=word_id).first_or_404()

    db.session.delete(deck_word)
    db.session.commit()

    # Check if AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json:
        return jsonify({
            'success': True,
            'message': 'Слово удалено из колоды'
        })

    flash('Слово удалено из колоды', 'success')
    return redirect(url_for('admin.quiz_deck_edit', deck_id=deck_id))


@admin.route('/quiz-decks/<int:deck_id>/words/reorder', methods=['POST'])
@login_required
def quiz_deck_reorder_words(deck_id):
    """Reorder words in deck"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    deck = QuizDeck.query.get_or_404(deck_id)
    word_ids = request.json.get('word_ids', [])

    for index, word_id in enumerate(word_ids):
        word = QuizDeckWord.query.get(word_id)
        if word and word.deck_id == deck_id:
            word.order_index = index

    db.session.commit()

    return jsonify({'success': True})


@admin.route('/api/words/search')
@login_required
def api_words_search():
    """API endpoint to search words for autocomplete in quiz deck editor"""
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 10)), 50)  # Max 50 for autocomplete

    # Base query - only words with translations
    words_query = CollectionWords.query.filter(
        CollectionWords.russian_word != None,
        CollectionWords.russian_word != ''
    )

    # Apply search filter
    if query and len(query) >= 2:
        from sqlalchemy import case

        words_query = words_query.filter(
            db.or_(
                CollectionWords.english_word.ilike(f'%{query}%'),
                CollectionWords.russian_word.ilike(f'%{query}%')
            )
        )

        # Smart sorting: exact match first, then starts with, then contains
        query_lower = query.lower()
        words_query = words_query.order_by(
            # Priority 1: Exact match (case-insensitive)
            case(
                (func.lower(CollectionWords.english_word) == query_lower, 1),
                (func.lower(CollectionWords.russian_word) == query_lower, 1),
                else_=10
            ),
            # Priority 2: Starts with query
            case(
                (func.lower(CollectionWords.english_word).like(f'{query_lower}%'), 2),
                (func.lower(CollectionWords.russian_word).like(f'{query_lower}%'), 2),
                else_=10
            ),
            # Priority 3: Alphabetically by English word
            CollectionWords.english_word
        )
    else:
        # No search query - return empty for autocomplete
        return jsonify([])

    words = words_query.limit(limit).all()

    results = [{
        'id': w.id,
        'english': w.english_word,
        'russian': w.russian_word
    } for w in words]

    return jsonify(results)
