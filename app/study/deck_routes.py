import bleach
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.study.blueprint import study, is_auto_deck

def _sanitize(value: str) -> str:
    """Strip all HTML tags from user-provided text to prevent stored XSS."""
    return bleach.clean(value, tags=[], strip=True)
from app.study.models import StudySettings
from app.utils.db import db
from app.words.forms import CollectionFilterForm
from app.words.models import Collection, CollectionWords, Topic
from app.modules.decorators import module_required
from app.study.services import DeckService, CollectionTopicService


@study.route('/my-decks/create', methods=['GET', 'POST'])
@login_required
@module_required('study')
def create_deck():
    if request.method == 'POST':
        title = _sanitize(request.form.get('title', '').strip())
        description = _sanitize(request.form.get('description', '').strip())
        is_public = request.form.get('is_public') == 'on'

        if not title:
            flash('Название колоды обязательно', 'danger')
            return redirect(url_for('study.create_deck'))

        deck = DeckService.create_deck(
            user_id=current_user.id,
            title=title,
            description=description,
            is_public=is_public
        )

        flash(f'Колода "{title}" успешно создана!', 'success')
        return redirect(url_for('study.edit_deck', deck_id=deck.id))

    return render_template('study/deck_create.html')


@study.route('/my-decks/<int:deck_id>/edit', methods=['GET', 'POST'])
@login_required
@module_required('study')
def edit_deck(deck_id):
    from app.study.models import QuizDeck, QuizDeckWord

    deck = QuizDeck.query.get_or_404(deck_id)

    if deck.user_id != current_user.id:
        flash('У вас нет прав для редактирования этой колоды', 'danger')
        return redirect(url_for('study.index'))

    if is_auto_deck(deck.title):
        flash('Нельзя редактировать автоматические колоды', 'warning')
        return redirect(url_for('study.index'))

    if request.method == 'POST':
        title = _sanitize(request.form.get('title', '').strip())
        description = _sanitize(request.form.get('description', '').strip())
        is_public = request.form.get('is_public') == 'on'

        new_words_limit_str = request.form.get('new_words_per_day', '').strip()
        reviews_limit_str = request.form.get('reviews_per_day', '').strip()

        try:
            new_words_per_day = int(new_words_limit_str) if new_words_limit_str else 0
            reviews_per_day = int(reviews_limit_str) if reviews_limit_str else 0
        except (ValueError, TypeError):
            flash('Лимиты должны быть числами', 'danger')
            words = deck.words.order_by(QuizDeckWord.order_index).all()
            return render_template('study/deck_edit.html', deck=deck, words=words)

        new_words_per_day = max(0, min(new_words_per_day, 1000))
        reviews_per_day = max(0, min(reviews_per_day, 10000))

        if not title:
            flash('Название колоды обязательно', 'danger')
            words = deck.words.order_by(QuizDeckWord.order_index).all()
            return render_template('study/deck_edit.html', deck=deck, words=words)

        updated_deck, error = DeckService.update_deck(
            deck_id=deck_id,
            user_id=current_user.id,
            title=title,
            description=description,
            is_public=is_public,
            generate_share=True,
            new_words_per_day=new_words_per_day,
            reviews_per_day=reviews_per_day
        )

        if error:
            flash(error, 'danger')
        else:
            flash('Колода успешно обновлена!', 'success')

        return redirect(url_for('study.edit_deck', deck_id=deck.id))

    words = deck.words.order_by(QuizDeckWord.order_index).all()
    return render_template('study/deck_edit.html', deck=deck, words=words)


@study.route('/my-decks/<int:deck_id>/settings', methods=['GET', 'POST'])
@login_required
@module_required('study')
def deck_settings(deck_id):
    from app.study.models import QuizDeck

    deck = QuizDeck.query.get_or_404(deck_id)

    if deck.user_id != current_user.id:
        flash('У вас нет прав для настройки этой колоды', 'danger')
        return redirect(url_for('study.index'))

    if request.method == 'POST':
        new_words_limit_str = request.form.get('new_words_per_day', '').strip()
        reviews_limit_str = request.form.get('reviews_per_day', '').strip()

        try:
            new_words_val = int(new_words_limit_str) if new_words_limit_str else None
            reviews_val = int(reviews_limit_str) if reviews_limit_str else None
        except (ValueError, TypeError):
            flash('Лимиты должны быть числами', 'danger')
            return redirect(url_for('study.deck_settings', deck_id=deck_id))

        if new_words_val is not None:
            new_words_val = max(0, min(new_words_val, 1000))
        if reviews_val is not None:
            reviews_val = max(0, min(reviews_val, 10000))

        deck.new_words_per_day = new_words_val
        deck.reviews_per_day = reviews_val

        db.session.commit()
        flash('Настройки колоды сохранены!', 'success')
        return redirect(url_for('study.index'))

    user_settings = StudySettings.query.filter_by(user_id=current_user.id).first()

    return render_template('study/deck_settings.html',
                           deck=deck,
                           user_settings=user_settings,
                           is_auto=is_auto_deck(deck.title))


@study.route('/my-decks/<int:deck_id>/delete', methods=['POST'])
@login_required
@module_required('study')
def delete_deck(deck_id):
    from app.study.models import QuizDeck

    deck = QuizDeck.query.get_or_404(deck_id)
    title = deck.title

    success, error = DeckService.delete_deck(deck_id, current_user.id)

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 403
        flash(error, 'danger')
        return redirect(url_for('study.index'))

    flash(f'Колода "{title}" успешно удалена', 'success')
    return redirect(url_for('study.index'))


@study.route('/decks/<int:deck_id>/copy', methods=['POST'])
@login_required
@module_required('study')
def copy_deck(deck_id):
    from app.study.models import QuizDeck

    original_deck = QuizDeck.query.get_or_404(deck_id)

    new_deck, error = DeckService.copy_deck(deck_id, current_user.id)

    if error:
        flash(error, 'info' if new_deck else 'danger')
        if new_deck:
            return redirect(url_for('study.edit_deck', deck_id=new_deck.id))
        return redirect(url_for('study.index'))

    flash(f'Колода "{original_deck.title}" успешно скопирована!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=new_deck.id))


@study.route('/my-decks/<int:deck_id>/words/add', methods=['POST'])
@login_required
@module_required('study')
def add_word_to_deck(deck_id):
    word_id = request.form.get('word_id', type=int)
    custom_english = _sanitize(request.form.get('custom_english', '').strip())
    custom_russian = _sanitize(request.form.get('custom_russian', '').strip())
    custom_sentences = _sanitize(request.form.get('custom_sentences', '').strip())

    deck_word, error = DeckService.add_word_to_deck(
        deck_id=deck_id,
        user_id=current_user.id,
        word_id=word_id,
        custom_english=custom_english,
        custom_russian=custom_russian,
        custom_sentences=custom_sentences if custom_sentences else None
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 400
        flash(error, 'danger' if 'не найден' in error else 'info')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        sentences = deck_word.sentences
        return jsonify({
            'success': True,
            'message': 'Слово добавлено в колоду!',
            'word': {
                'id': deck_word.id,
                'english': deck_word.english_word,
                'russian': deck_word.russian_word,
                'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None or deck_word.custom_sentences is not None,
                'sentences': sentences[:150] if sentences and len(sentences) > 150 else sentences
            }
        })

    flash('Слово добавлено в колоду!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


@study.route('/my-decks/<int:deck_id>/words/<int:word_id>/edit', methods=['POST'])
@login_required
@module_required('study')
def edit_deck_word(deck_id, word_id):
    custom_english = _sanitize(request.form.get('custom_english', '').strip())
    custom_russian = _sanitize(request.form.get('custom_russian', '').strip())
    custom_sentences = _sanitize(request.form.get('custom_sentences', '').strip())

    deck_word, error = DeckService.edit_deck_word(
        deck_id=deck_id,
        deck_word_id=word_id,
        user_id=current_user.id,
        custom_english=custom_english,
        custom_russian=custom_russian,
        custom_sentences=custom_sentences if custom_sentences else None
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 400
        flash(error, 'danger')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': 'Слово успешно обновлено!',
            'word': {
                'id': deck_word.id,
                'english': deck_word.english_word,
                'russian': deck_word.russian_word,
                'has_custom': deck_word.custom_english is not None or deck_word.custom_russian is not None or deck_word.custom_sentences is not None,
                'sentences': deck_word.sentences
            }
        })

    flash('Слово успешно обновлено!', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


@study.route('/my-decks/<int:deck_id>/words/<int:word_id>/delete', methods=['POST'])
@login_required
@module_required('study')
def remove_word_from_deck(deck_id, word_id):
    success, error = DeckService.remove_word_from_deck(
        deck_id=deck_id,
        deck_word_id=word_id,
        user_id=current_user.id
    )

    if error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': error}), 403
        flash(error, 'danger')
        return redirect(url_for('study.edit_deck', deck_id=deck_id))

    flash('Слово удалено из колоды', 'success')
    return redirect(url_for('study.edit_deck', deck_id=deck_id))


# ============ Collections & Topics ============


@study.route('/collections')
@login_required
def collections():
    form = CollectionFilterForm(request.args)

    topic_id = request.args.get('topic')
    topic_id = int(topic_id) if topic_id and topic_id.isdigit() else None
    search = request.args.get('search')

    collections_data = CollectionTopicService.get_collections_with_stats(
        user_id=current_user.id,
        topic_id=topic_id,
        search=search
    )

    for data in collections_data:
        data['collection'].words_in_study = data['words_in_study']
        data['collection'].topic_list = data['topics']

    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'study/collections.html',
        collections=[d['collection'] for d in collections_data],
        form=form,
        topics=topics,
        selected_topic=topic_id
    )


@study.route('/collections/<int:collection_id>')
@login_required
def collection_details(collection_id):
    collection = Collection.query.get_or_404(collection_id)

    words_data = CollectionTopicService.get_collection_words_with_status(
        collection_id=collection_id,
        user_id=current_user.id
    )

    words = [data['word'] for data in words_data]
    for i, word in enumerate(words):
        word.is_studying = words_data[i]['is_studying']

    topics = collection.topics

    return render_template(
        'study/collections_details.html',
        collection=collection,
        words=words,
        topics=topics
    )


@study.route('/add_collection/<int:collection_id>', methods=['POST'])
@login_required
def add_collection(collection_id):
    collection = Collection.query.get_or_404(collection_id)

    added_count, message = CollectionTopicService.add_collection_to_study(
        collection_id=collection_id,
        user_id=current_user.id
    )

    if added_count > 0:
        flash(_('%(count)d words from "%(name)s" collection added to your study list!',
                count=added_count, name=collection.name), 'success')
    else:
        flash(_('All words from this collection are already in your study list.'), 'info')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'added_count': added_count,
            'message': _('%(count)d words added to your study list!', count=added_count)
        })

    return redirect(url_for('study.collections'))


@study.route('/topics')
@login_required
def topics():
    topics_data = CollectionTopicService.get_topics_with_stats(current_user.id)

    for data in topics_data:
        data['topic'].word_count = data['word_count']
        data['topic'].words_in_study = data['words_in_study']

    return render_template(
        'study/topics.html',
        topics=[d['topic'] for d in topics_data]
    )


@study.route('/topics/<int:topic_id>')
@login_required
def topic_details(topic_id):
    topic, words_data, related_collections = CollectionTopicService.get_topic_words_with_status(
        topic_id=topic_id,
        user_id=current_user.id
    )

    if not topic:
        from flask import abort
        abort(404)

    words = [data['word'] for data in words_data]
    for i, word in enumerate(words):
        word.is_studying = words_data[i]['is_studying']

    return render_template(
        'study/topic_details.html',
        topic=topic,
        words=words,
        related_collections=related_collections
    )


@study.route('/add_topic/<int:topic_id>', methods=['POST'])
@login_required
def add_topic(topic_id):
    topic = Topic.query.get_or_404(topic_id)

    added_count, message = CollectionTopicService.add_topic_to_study(
        topic_id=topic_id,
        user_id=current_user.id
    )

    if added_count > 0:
        flash(_('%(count)d words from "%(name)s" topic added to your study list!',
                count=added_count, name=topic.name), 'success')
    else:
        flash(_('All words from this topic are already in your study list.'), 'info')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'added_count': added_count,
            'message': _('%(count)d words added to your study list!', count=added_count)
        })

    return redirect(url_for('study.topics'))


# ============ Deck API Endpoints ============


@study.route('/api/collections-topics')
@login_required
def api_collections_topics():
    collections_list = Collection.query.order_by(Collection.name).all()
    topics_list = Topic.query.order_by(Topic.name).all()

    return jsonify({
        'collections': [{
            'id': c.id,
            'name': c.name,
            'description': c.description or '',
            'word_count': len(c.words)
        } for c in collections_list],
        'topics': [{
            'id': t.id,
            'name': t.name,
            'description': t.description or '',
            'word_count': len(t.words)
        } for t in topics_list]
    })


@study.route('/api/decks/<int:deck_id>/add-from-collection', methods=['POST'])
@login_required
def api_add_from_collection(deck_id):
    data = request.get_json()
    if not data or not data.get('collection_id'):
        return jsonify({'success': False, 'message': 'collection_id is required'}), 400

    collection = Collection.query.get(data['collection_id'])
    if not collection:
        return jsonify({'success': False, 'message': 'Collection not found'}), 404

    word_ids = [w.id for w in collection.words]
    added, skipped = DeckService.add_bulk_words_to_deck(deck_id, current_user.id, word_ids)

    return jsonify({
        'success': True,
        'added_count': added,
        'skipped_count': skipped,
        'message': f'Добавлено {added} слов из "{collection.name}"' if added > 0
                   else f'Все слова из "{collection.name}" уже в колоде'
    })


@study.route('/api/decks/<int:deck_id>/add-from-topic', methods=['POST'])
@login_required
def api_add_from_topic(deck_id):
    data = request.get_json()
    if not data or not data.get('topic_id'):
        return jsonify({'success': False, 'message': 'topic_id is required'}), 400

    topic = Topic.query.get(data['topic_id'])
    if not topic:
        return jsonify({'success': False, 'message': 'Topic not found'}), 404

    word_ids = [w.id for w in topic.words]
    added, skipped = DeckService.add_bulk_words_to_deck(deck_id, current_user.id, word_ids)

    return jsonify({
        'success': True,
        'added_count': added,
        'skipped_count': skipped,
        'message': f'Добавлено {added} слов из темы "{topic.name}"' if added > 0
                   else f'Все слова из темы "{topic.name}" уже в колоде'
    })


@study.route('/api/my-decks')
@login_required
def api_get_my_decks():
    from app.study.models import QuizDeck

    decks = QuizDeck.query.filter_by(user_id=current_user.id).order_by(
        QuizDeck.updated_at.desc()
    ).all()

    result = []
    for deck in decks:
        if DeckService.is_auto_deck(deck.title):
            continue

        result.append({
            'id': deck.id,
            'name': deck.title,
            'word_count': deck.word_count,
            'is_public': deck.is_public
        })

    return jsonify({
        'success': True,
        'decks': result,
        'default_deck_id': current_user.default_study_deck_id
    })


@study.route('/api/default-deck', methods=['GET', 'POST'])
@login_required
def api_default_deck():
    from app.study.models import QuizDeck

    if request.method == 'POST':
        data = request.get_json()
        deck_id = data.get('deck_id')

        if deck_id is not None:
            deck = QuizDeck.query.filter_by(id=deck_id, user_id=current_user.id).first()
            if not deck:
                return jsonify({
                    'success': False,
                    'error': 'Колода не найдена'
                }), 404

        current_user.default_study_deck_id = deck_id
        db.session.commit()

    default_deck_name = None
    if current_user.default_study_deck_id:
        from app.study.models import QuizDeck
        deck = QuizDeck.query.get(current_user.default_study_deck_id)
        if deck:
            default_deck_name = deck.title
        else:
            current_user.default_study_deck_id = None
            db.session.commit()

    return jsonify({
        'success': True,
        'default_deck_id': current_user.default_study_deck_id,
        'default_deck_name': default_deck_name
    })


@study.route('/api/decks/create', methods=['POST'])
@login_required
def api_create_deck():
    data = request.get_json()
    name = _sanitize(data.get('name', '').strip())

    if not name:
        return jsonify({
            'success': False,
            'error': 'Название колоды обязательно'
        }), 400

    if len(name) > 200:
        return jsonify({
            'success': False,
            'error': 'Название колоды слишком длинное'
        }), 400

    deck = DeckService.create_deck(
        user_id=current_user.id,
        title=name,
        description='',
        is_public=False
    )

    return jsonify({
        'success': True,
        'deck': {
            'id': deck.id,
            'name': deck.title,
            'word_count': 0,
            'is_public': False
        }
    })


@study.route('/api/decks/<int:deck_id>/add-word', methods=['POST'])
@login_required
def api_add_word_to_deck(deck_id):
    data = request.get_json()
    word_id = data.get('word_id')

    if not word_id:
        return jsonify({
            'success': False,
            'error': 'word_id обязателен'
        }), 400

    word = CollectionWords.query.get(word_id)
    if not word:
        return jsonify({
            'success': False,
            'error': 'Слово не найдено'
        }), 404

    deck_word, error = DeckService.add_word_to_deck(
        deck_id=deck_id,
        user_id=current_user.id,
        word_id=word_id,
        custom_english=word.english_word,
        custom_russian=word.russian_word,
        custom_sentences=word.sentences
    )

    if error:
        if 'уже в колоде' in error:
            return jsonify({
                'success': True,
                'message': error,
                'already_exists': True
            })
        return jsonify({
            'success': False,
            'error': error
        }), 400

    return jsonify({
        'success': True,
        'message': 'Слово добавлено в колоду'
    })


@study.route('/api/add-phrase-to-deck', methods=['POST'])
@login_required
def api_add_phrase_to_deck():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data'}), 400

    english = _sanitize((data.get('english') or '').strip())
    russian = _sanitize((data.get('russian') or '').strip())
    context = _sanitize((data.get('context') or '').strip())

    if not english or not russian:
        return jsonify({'success': False, 'error': 'english and russian required'}), 400

    deck_id = current_user.default_study_deck_id
    if not deck_id:
        return jsonify({'success': False, 'error': 'no_default_deck'}), 200

    deck_word, error = DeckService.add_word_to_deck(
        deck_id=deck_id,
        user_id=current_user.id,
        word_id=None,
        custom_english=english,
        custom_russian=russian,
        custom_sentences=context if context else None
    )

    if error:
        return jsonify({'success': False, 'error': error}), 200

    return jsonify({
        'success': True,
        'message': f'"{english}" added to your deck'
    })
