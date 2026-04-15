# app/curriculum/routes/card_lessons.py

import json
import logging
from datetime import UTC, datetime

from flask import jsonify, render_template, request
from flask_login import current_user, login_required
from marshmallow import ValidationError

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.routes.lessons import lessons_bp
from app.curriculum.security import require_lesson_access
from app.curriculum.service import (
    get_card_session_for_lesson, process_card_review_for_lesson, sync_lesson_cards_to_words,
)
from app.curriculum.validators import SRSReviewSchema, validate_request_data
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


def _build_cards_for_words(word_objects: list, user_id: int) -> list[dict]:
    """Build card data list for words, one card per UserCardDirection.

    Looks up existing UserWord/UserCardDirection records, creates eng-rus
    direction if none exists, and produces card dicts with proper
    direction/front/back/SRS fields.
    """
    if not word_objects:
        return []

    word_ids = [w.id for w in word_objects]

    user_words = UserWord.query.filter(
        UserWord.user_id == user_id,
        UserWord.word_id.in_(word_ids)
    ).all()
    user_word_map = {uw.word_id: uw for uw in user_words}

    user_word_ids = [uw.id for uw in user_words]
    directions_by_word: dict[int, list] = {}
    if user_word_ids:
        rows = db.session.query(UserCardDirection, UserWord.word_id).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(UserWord.id.in_(user_word_ids)).all()
        for dir_obj, word_id in rows:
            directions_by_word.setdefault(word_id, []).append(dir_obj)

    existing_word_ids = set(directions_by_word.keys())
    needs_flush = False
    for word in word_objects:
        if word.id not in directions_by_word:
            uw = user_word_map.get(word.id)
            if not uw:
                uw = UserWord.get_or_create(user_id, word.id)
                user_word_map[word.id] = uw
            dir_obj = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
            db.session.add(dir_obj)
            directions_by_word[word.id] = [dir_obj]
            needs_flush = True

    if needs_flush:
        db.session.flush()

        from app.study.deck_utils import ensure_word_in_default_deck
        for word in word_objects:
            if word.id not in existing_word_ids:
                uw = user_word_map.get(word.id)
                ensure_word_in_default_deck(user_id, word.id, uw.id if uw else None)
        db.session.flush()

    cards_list = []
    for word in word_objects:
        from app.utils.audio import parse_audio_filename
        audio_file = parse_audio_filename(word.listening) if word.listening else None
        if not audio_file and word.get_download == 1:
            audio_file = f"{word.english_word.lower().replace(' ', '_')}.mp3"

        example_en = ''
        example_ru = ''
        if word.sentences:
            try:
                sentences_data = json.loads(word.sentences) if isinstance(word.sentences, str) else word.sentences
                if isinstance(sentences_data, list) and len(sentences_data) > 0:
                    first_sentence = sentences_data[0]
                    if isinstance(first_sentence, dict):
                        example_en = first_sentence.get('en', '')
                        example_ru = first_sentence.get('ru', '')
            except Exception:
                logger.exception("Failed to parse word sentences for word %s", word.id)

        for dir_obj in directions_by_word.get(word.id, []):
            if dir_obj.direction == 'eng-rus':
                front = word.english_word
                back = word.russian_word
            else:
                front = word.russian_word
                back = word.english_word

            cards_list.append({
                'id': word.id,
                'word_id': word.id,
                'direction_id': dir_obj.id,
                'direction': dir_obj.direction,
                'front': front,
                'back': back,
                'word': front,
                'translation': back,
                'english': word.english_word,
                'russian': word.russian_word,
                'listening': word.listening or '',
                'sentences': word.sentences or '',
                'example': example_en,
                'example_en': example_en,
                'example_ru': example_ru,
                'examples': f"{example_en}|{example_ru}" if example_en and example_ru else '',
                'usage': '',
                'hint': '',
                'is_new': dir_obj.repetitions == 0 and dir_obj.last_reviewed is None,
                'status': dir_obj.state or 'new',
                'interval': dir_obj.interval or 0,
                'ease_factor': dir_obj.ease_factor or 2.5,
                'repetitions': dir_obj.repetitions or 0,
                'session_attempts': dir_obj.session_attempts or 0,
                'audio': audio_file,
                'audio_url': f"/static/audio/{audio_file}" if audio_file else None,
                'get_download': 1 if word.get_download == 1 else 0,
            })

    return cards_list


# =============================================================================
# RENDER FUNCTION - called from main.py without redirects
# =============================================================================

def render_card_lesson(lesson):
    """Рендер card урока"""
    from app.words.models import CollectionWordLink

    if lesson.type not in ['card', 'flashcards']:
        from flask import abort
        abort(400, "This is not a card lesson")

    success, message, updated, created = sync_lesson_cards_to_words(lesson)
    if success and (created > 0 or updated > 0):
        logger.info(f"Synced lesson {lesson.id} cards: {message}")
        db.session.refresh(lesson)

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    next_lesson = None
    if lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number > lesson.number
        ).order_by(Lessons.number).first()

    word_ids = []

    if lesson.collection_id:
        word_links = CollectionWordLink.query.filter_by(
            collection_id=lesson.collection_id
        ).all()
        word_ids = [link.word_id for link in word_links]

    if lesson.content:
        try:
            content = json.loads(lesson.content) if isinstance(lesson.content, str) else lesson.content
            if isinstance(content, dict) and 'cards' in content:
                for card in content['cards']:
                    if isinstance(card, dict) and 'word_id' in card:
                        word_ids.append(card['word_id'])
        except Exception as e:
            logger.error(f"Error parsing lesson content: {e}")

    if not word_ids and lesson.module_id and lesson.number is not None:
        previous_lessons = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number < lesson.number,
            Lessons.type.in_(['vocabulary', 'card', 'flashcards'])
        ).all()

        for prev_lesson in previous_lessons:
            if prev_lesson.collection_id:
                word_links = CollectionWordLink.query.filter_by(
                    collection_id=prev_lesson.collection_id
                ).all()
                word_ids.extend([link.word_id for link in word_links])
            elif prev_lesson.content:
                try:
                    prev_content = json.loads(prev_lesson.content) if isinstance(prev_lesson.content, str) else prev_lesson.content
                    if isinstance(prev_content, dict) and 'cards' in prev_content:
                        for card in prev_content['cards']:
                            if isinstance(card, dict) and 'word_id' in card:
                                word_ids.append(card['word_id'])
                except Exception:
                    logger.exception("Failed to parse lesson content for word_ids")

        word_ids = list(set(word_ids))

    cards_list = []
    if word_ids:
        word_objects = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()
        cards_list = _build_cards_for_words(word_objects, current_user.id)

    next_review_time = None
    if len(cards_list) == 0:
        if word_ids:
            user_words = UserWord.query.filter(
                UserWord.user_id == current_user.id,
                UserWord.word_id.in_(word_ids),
                UserWord.next_review.isnot(None)
            ).order_by(UserWord.next_review.asc()).first()

            if user_words and user_words.next_review:
                time_diff = user_words.next_review - datetime.now(UTC)
                hours = int(time_diff.total_seconds() / 3600)
                if hours < 1:
                    minutes = int(time_diff.total_seconds() / 60)
                    next_review_time = f"{minutes} мин" if minutes > 0 else "скоро"
                elif hours < 24:
                    next_review_time = f"{hours} ч"
                else:
                    days = int(hours / 24)
                    next_review_time = f"{days} д"

    cards_data = {
        'cards': cards_list,
        'srs_settings': {
            'new_cards_limit': 20,
            'review_cards_limit': 50,
            'show_hint_time': 5
        },
        'lesson_settings': {},
        'stats': {},
        'next_review_time': next_review_time
    }

    fc_cards = []
    for c in cards_list:
        fc_cards.append({
            'word_id': c['word_id'],
            'direction_id': c.get('direction_id'),
            'direction': c.get('direction', 'eng-rus'),
            'front': c['front'],
            'back': c['back'],
            'audio_url': c.get('audio_url'),
            'example': c.get('example_en', ''),
            'example_translation': c.get('example_ru', ''),
            'book_context': None,
            'status': c.get('status', 'new'),
            'is_new': c.get('is_new', True),
            'word': c.get('word', c['front']),
            'translation': c.get('translation', c['back']),
        })

    next_lesson_url = f"/learn/{next_lesson.id}/" if next_lesson else None
    if lesson.module and lesson.module.level:
        back_url = f"/learn/{lesson.module.level.code.lower()}/#module-{lesson.module.number}"
    else:
        back_url = '/learn/'

    return render_template(
        'curriculum/lessons/card.html',
        lesson=lesson,
        progress=progress,
        cards_data=cards_data,
        next_lesson=next_lesson,
        lesson_id=lesson.id,
        fc_title=f"Урок {lesson.order_index}" if hasattr(lesson, 'order_index') and lesson.order_index else lesson.title,
        fc_back_url=back_url,
        fc_cards=fc_cards,
        fc_grade_url='/study/api/update-study-item',
        fc_complete_url=f'/curriculum/lessons/{lesson.id}/complete-srs',
        fc_complete_payload='(function(sid, stats) { var total = stats ? stats.total : 0; var incorrect = stats ? stats.incorrect : 0; return { cards_studied: total, accuracy: total > 0 ? Math.round(((total - incorrect) / total) * 100) : 0 }; })',
        fc_on_complete_url=next_lesson_url or '/learn/',
        fc_on_complete_text='Следующий урок' if next_lesson else 'К обучению',
        fc_session_id=None,
        fc_show_examples=True,
        fc_show_audio=True,
        fc_show_book_context=False,
        fc_nothing_to_study=len(fc_cards) == 0,
        fc_extra_study=True,
    )


# =============================================================================
# ROUTE HANDLERS
# =============================================================================

@lessons_bp.route('/lesson/<int:lesson_id>/card')
@login_required
@require_lesson_access
def card_lesson(lesson_id):
    """Display SRS card lesson"""
    from app.words.models import CollectionWordLink

    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type not in ['card', 'flashcards']:
        from flask import abort
        abort(400, "This is not a card lesson")

    success, message, updated, created = sync_lesson_cards_to_words(lesson)
    if success and (created > 0 or updated > 0):
        logger.info(f"Synced lesson {lesson_id} cards: {message}")
        db.session.refresh(lesson)

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    next_lesson = None
    if lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number > lesson.number
        ).order_by(Lessons.number).first()

    word_ids = []

    if lesson.collection_id:
        word_links = CollectionWordLink.query.filter_by(
            collection_id=lesson.collection_id
        ).all()
        word_ids = [link.word_id for link in word_links]

    if lesson.content:
        try:
            content = json.loads(lesson.content) if isinstance(lesson.content, str) else lesson.content
            if isinstance(content, dict) and 'cards' in content:
                for card in content['cards']:
                    if isinstance(card, dict) and 'word_id' in card:
                        word_ids.append(card['word_id'])
        except Exception as e:
            logger.error(f"Error parsing lesson content: {e}")

    if not word_ids and lesson.module_id and lesson.number is not None:
        previous_lessons = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number < lesson.number,
            Lessons.type.in_(['vocabulary', 'card', 'flashcards'])
        ).all()

        for prev_lesson in previous_lessons:
            if prev_lesson.collection_id:
                word_links = CollectionWordLink.query.filter_by(
                    collection_id=prev_lesson.collection_id
                ).all()
                word_ids.extend([link.word_id for link in word_links])
            elif prev_lesson.content:
                try:
                    prev_content = json.loads(prev_lesson.content) if isinstance(prev_lesson.content, str) else prev_lesson.content
                    if isinstance(prev_content, dict) and 'cards' in prev_content:
                        for card in prev_content['cards']:
                            if isinstance(card, dict) and 'word_id' in card:
                                word_ids.append(card['word_id'])
                except Exception:
                    logger.exception("Failed to parse lesson content for word_ids")

        word_ids = list(set(word_ids))

    cards_list = []
    if word_ids:
        word_objects = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()
        cards_list = _build_cards_for_words(word_objects, current_user.id)

    next_review_time = None
    if len(cards_list) == 0:
        if word_ids:
            user_words = UserWord.query.filter(
                UserWord.user_id == current_user.id,
                UserWord.word_id.in_(word_ids),
                UserWord.next_review.isnot(None)
            ).order_by(UserWord.next_review.asc()).first()

            if user_words and user_words.next_review:
                time_diff = user_words.next_review - datetime.now(UTC)
                hours = int(time_diff.total_seconds() / 3600)
                if hours < 1:
                    minutes = int(time_diff.total_seconds() / 60)
                    next_review_time = f"{minutes} мин" if minutes > 0 else "скоро"
                elif hours < 24:
                    next_review_time = f"{hours} ч"
                else:
                    days = int(hours / 24)
                    next_review_time = f"{days} д"

    cards_data = {
        'cards': cards_list,
        'srs_settings': {
            'new_cards_limit': 20,
            'review_cards_limit': 50,
            'show_hint_time': 5
        },
        'lesson_settings': {},
        'stats': {},
        'next_review_time': next_review_time
    }

    fc_cards: list[dict] = []
    for c in cards_list:
        fc_cards.append({
            'word_id': c['word_id'],
            'direction_id': c.get('direction_id'),
            'direction': c.get('direction', 'eng-rus'),
            'front': c['front'],
            'back': c['back'],
            'audio_url': c.get('audio_url'),
            'example': c.get('example_en', ''),
            'example_translation': c.get('example_ru', ''),
            'book_context': None,
            'status': c.get('status', 'new'),
            'is_new': c.get('is_new', True),
            'word': c.get('word', c['front']),
            'translation': c.get('translation', c['back']),
        })

    next_lesson_url = f"/learn/{next_lesson.id}/" if next_lesson else None
    if lesson.module and lesson.module.level:
        back_url = f"/learn/{lesson.module.level.code.lower()}/#module-{lesson.module.number}"
    else:
        back_url = '/learn/'

    return render_template(
        'curriculum/lessons/card.html',
        lesson=lesson,
        progress=progress,
        cards_data=cards_data,
        next_lesson=next_lesson,
        lesson_id=lesson.id,
        fc_title=f"Урок {lesson.order_index}" if hasattr(lesson, 'order_index') and lesson.order_index else lesson.title,
        fc_back_url=back_url,
        fc_cards=fc_cards,
        fc_grade_url='/study/api/update-study-item',
        fc_complete_url=f'/curriculum/lessons/{lesson.id}/complete-srs',
        fc_complete_payload='(function(sid, stats) { var total = stats ? stats.total : 0; var incorrect = stats ? stats.incorrect : 0; return { cards_studied: total, accuracy: total > 0 ? Math.round(((total - incorrect) / total) * 100) : 0 }; })',
        fc_on_complete_url=next_lesson_url or '/learn/',
        fc_on_complete_text='Следующий урок' if next_lesson else 'К обучению',
        fc_session_id=None,
        fc_show_examples=True,
        fc_show_audio=True,
        fc_show_book_context=False,
        fc_nothing_to_study=len(fc_cards) == 0,
        fc_extra_study=True,
    )


@lessons_bp.route('/lessons/<int:lesson_id>/complete-srs', methods=['POST'])
@login_required
@require_lesson_access
def complete_srs_session(lesson_id):
    """Complete SRS card session and save progress"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        lesson = Lessons.query.get_or_404(lesson_id)

        progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=lesson.id
        ).first()

        if not progress:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress'
            )
            db.session.add(progress)

        cards_studied = data.get('cards_studied', 0)
        accuracy = data.get('accuracy', 0)

        if cards_studied > 0:
            progress.status = 'completed'
            progress.score = round(accuracy, 2)
            progress.completed_at = datetime.now(UTC)

        db.session.commit()

        return jsonify({
            'success': True,
            'cards_studied': cards_studied,
            'accuracy': accuracy
        })

    except Exception as e:
        logger.error(f"Error completing SRS session: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500


@lessons_bp.route('/api/lesson/<int:lesson_id>/card/review', methods=['POST'])
@login_required
@require_lesson_access
def review_card(lesson_id):
    """Process card review with validation"""
    try:
        data = request.get_json()

        is_valid, error_msg, cleaned_data = validate_request_data(
            SRSReviewSchema, data
        )

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        result = process_card_review_for_lesson(
            lesson_id,
            current_user.id,
            cleaned_data['word_id'],
            cleaned_data['direction'],
            cleaned_data['quality']
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error processing card review: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


@lessons_bp.route('/api/rate-card', methods=['POST'])
@login_required
def rate_card_api():
    """Rate a card for SRS lesson"""
    try:
        data = request.get_json()

        lesson_id = data.get('lesson_id')
        word_id = data.get('word_id')
        direction = data.get('direction')
        rating = data.get('rating')

        logger.info(
            f"Rate card API called with: lesson_id={lesson_id}, word_id={word_id}, direction={direction}, rating={rating}")

        if not all([lesson_id, word_id, direction, rating is not None]):
            logger.error("Missing required fields in rate card request")
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        lesson = Lessons.query.get(lesson_id)
        if not lesson:
            logger.error(f"Lesson {lesson_id} not found")
            return jsonify({'success': False, 'error': 'Lesson not found'}), 404

        result = process_card_review_for_lesson(
            lesson_id,
            current_user.id,
            word_id,
            direction,
            rating
        )

        logger.info(f"Rate card result: {result}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error rating card: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Server error'}), 500


@lessons_bp.route('/api/lesson/<int:lesson_id>/next-review-time', methods=['GET'])
@login_required
def get_next_review_time(lesson_id):
    """Get next review time for lesson"""
    try:
        lesson = Lessons.query.get_or_404(lesson_id)

        session_data = get_card_session_for_lesson(lesson_id, current_user.id)

        return jsonify({
            'next_review_time': session_data.get('next_review_time', 'Нет запланированных повторений')
        })

    except Exception as e:
        logger.error(f"Error getting next review time: {str(e)}")
        return jsonify({'next_review_time': 'Ошибка получения данных'}), 500
