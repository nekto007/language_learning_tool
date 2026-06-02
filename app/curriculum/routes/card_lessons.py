# app/curriculum/routes/card_lessons.py

import json
import logging
from datetime import UTC, datetime

from flask import jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from app.curriculum.models import LessonProgress, Lessons
from app.curriculum.routes.lessons import lessons_bp
from app.curriculum.security import require_lesson_access
from app.curriculum.service import (
    get_card_session_for_lesson,
    process_card_review_for_lesson,
)
from app.curriculum.validators import SRSReviewSchema, validate_request_data
from app.srs.constants import (
    DEFAULT_EASE_FACTOR,
    DIRECTION_ENG_RUS,
    DIRECTION_RUS_ENG,
    CardState,
)
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


def _build_display_cards_from_content(content: dict) -> list[dict]:
    """Build non-SRS flashcards directly from lesson JSON.

    This keeps card lesson GET requests read-only when imported content has not
    been synced into ``CollectionWords`` yet. Cards with a real ``word_id`` are
    still handled through the normal SRS path.
    """
    if not isinstance(content, dict):
        return []

    cards = content.get('cards') or []
    if not isinstance(cards, list):
        return []

    result = []
    for idx, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        front = (card.get('front') or card.get('english') or '').strip()
        back = (card.get('back') or card.get('russian') or '').strip()
        if not front or not back:
            continue

        audio = card.get('audio') or card.get('audio_url')
        audio_url = None
        if isinstance(audio, str) and audio:
            from app.utils.audio import parse_audio_filename
            audio_file = parse_audio_filename(audio) or audio
            audio_url = audio if audio.startswith('/static/') else f"/static/audio/{audio_file}"

        result.append({
            'id': card.get('id') or f"lesson-card-{idx}",
            'word_id': None,
            'direction_id': None,
            'direction': 'eng-rus',
            'front': front,
            'back': back,
            'word': front,
            'translation': back,
            'english': card.get('english') or front,
            'russian': card.get('russian') or back,
            'example': card.get('example') or '',
            'example_en': card.get('example') or '',
            'example_ru': card.get('example_translation') or '',
            'audio_url': audio_url,
            'is_new': True,
            'status': 'new',
        })
    return result


def _extract_word_example(word) -> tuple[str, str]:
    """Return (english_example, russian_example) tolerating multiple legacy
    storage shapes for ``CollectionWords.sentences``.

    Shapes seen in the wild:
      * Modern JSON: ``[{"en": "...", "ru": "..."}, ...]``
      * Legacy plain-string: ``"He is here.<br>Он здесь."`` (split by ``<br>``,
        or ``\\n``, or `` / ``).
      * Already-deserialised list/dict — returned as-is.

    Failures are logged at debug-level (not as full ERROR stack-traces),
    because malformed/empty sentences are common in older content and not
    worth spamming the log for. The card-lesson UI just hides examples
    when the function returns empty strings.
    """
    raw = getattr(word, 'sentences', None)
    if not raw:
        return '', ''

    # Already structured?
    if isinstance(raw, list):
        first = raw[0] if raw else None
        if isinstance(first, dict):
            return first.get('en', '') or '', first.get('ru', '') or ''
        return '', ''
    if isinstance(raw, dict):
        return raw.get('en', '') or '', raw.get('ru', '') or ''

    if not isinstance(raw, str):
        return '', ''

    text = raw.strip()
    if not text:
        return '', ''

    # JSON first — only attempt if the string actually looks like JSON.
    if text[0] in '[{':
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0].get('en', '') or '', parsed[0].get('ru', '') or ''
            if isinstance(parsed, dict):
                return parsed.get('en', '') or '', parsed.get('ru', '') or ''
        except (ValueError, TypeError):
            logger.debug("word %s: sentences looked JSON-shaped but failed to parse",
                         getattr(word, 'id', '?'))

    # Legacy plain-string formats: «English<br>Russian», or «English / Russian»,
    # or «English\nRussian». Split on first delimiter, keep both halves.
    for delim in ('<br>', '<BR>', '<br/>', '<br />', '\n', ' / '):
        if delim in text:
            en, _, ru = text.partition(delim)
            return en.strip(), ru.strip()

    # Unknown shape — give whole string as English example, leave Russian empty.
    return text, ''


def _build_cards_for_words(
    word_objects: list,
    user_id: int,
    activate_srs: bool = True,
) -> list[dict]:
    """Build card data list for words, one card per UserCardDirection.

    Looks up existing UserWord/UserCardDirection records, creates eng-rus
    direction if none exists, and produces card dicts with proper
    direction/front/back/SRS fields.

    When ``activate_srs=False`` the function does not create any new
    ``UserWord`` or ``UserCardDirection`` rows: words that have never
    been touched by SRS are emitted as display-only cards with
    ``direction_id=None`` and ``is_new=True``. Used by the linear daily
    plan's card lesson when ``srs_budget_remaining == 0`` so curriculum
    vocabulary can still be shown without consuming tomorrow's budget.
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
    if activate_srs:
        for word in word_objects:
            if word.id not in directions_by_word:
                uw = user_word_map.get(word.id)
                if not uw:
                    uw = UserWord.get_or_create(user_id, word.id)
                    user_word_map[word.id] = uw
                dir_eng_rus = UserCardDirection(
                    user_word_id=uw.id,
                    direction=DIRECTION_ENG_RUS,
                    source='lesson_vocab',
                    ease_factor=DEFAULT_EASE_FACTOR,
                    state=CardState.NEW.value,
                )
                dir_rus_eng = UserCardDirection(
                    user_word_id=uw.id,
                    direction=DIRECTION_RUS_ENG,
                    source='lesson_vocab',
                    ease_factor=DEFAULT_EASE_FACTOR,
                    state=CardState.NEW.value,
                )
                db.session.add(dir_eng_rus)
                db.session.add(dir_rus_eng)
                directions_by_word[word.id] = [dir_eng_rus, dir_rus_eng]
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

        example_en, example_ru = _extract_word_example(word)

        directions = directions_by_word.get(word.id, [])
        if directions:
            for dir_obj in directions:
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
                    'is_new': dir_obj.state == CardState.NEW.value,
                    'status': dir_obj.state or 'new',
                    'interval': dir_obj.interval or 0,
                    'ease_factor': dir_obj.ease_factor or 2.5,
                    'repetitions': dir_obj.repetitions or 0,
                    'session_attempts': dir_obj.session_attempts or 0,
                    'audio': audio_file,
                    'audio_url': f"/static/audio/{audio_file}" if audio_file else None,
                    'get_download': 1 if word.get_download == 1 else 0,
                })
        else:
            # activate_srs=False path: emit a display-only card for a word
            # that has no UserCardDirection yet. No SM-2 scheduling, no deck
            # enrollment, no SRS budget consumption.
            cards_list.append({
                'id': word.id,
                'word_id': word.id,
                'direction_id': None,
                'direction': 'eng-rus',
                'front': word.english_word,
                'back': word.russian_word,
                'word': word.english_word,
                'translation': word.russian_word,
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
                'is_new': True,
                'status': 'new',
                'interval': 0,
                'ease_factor': DEFAULT_EASE_FACTOR,
                'repetitions': 0,
                'session_attempts': 0,
                'audio': audio_file,
                'audio_url': f"/static/audio/{audio_file}" if audio_file else None,
                'get_download': 1 if word.get_download == 1 else 0,
            })

    return cards_list


def render_card_lesson(lesson):
    """Рендер card урока"""
    from app.words.models import CollectionWordLink

    if lesson.type not in ['card', 'flashcards']:
        from flask import abort
        abort(400, "This is not a card lesson")

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    # ?reset=true сбрасывает LessonProgress в in_progress, чтобы пользователь
    # мог пройти карточный урок заново через confirm-модалку. SRS-state
    # отдельных карт при этом не трогаем (живёт в UserCardDirection
    # независимо от LessonProgress). XP не начислится дважды — там idempotent
    # dedup через StreakEvent.
    reset_progress = request.args.get('reset') == 'true'
    if reset_progress and progress and progress.status == 'completed':
        progress.status = 'in_progress'
        progress.score = None
        progress.data = None
        progress.completed_at = None
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    next_lesson = None
    if lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == lesson.module_id,
            Lessons.number > lesson.number
        ).order_by(Lessons.number).first()

    word_ids = []
    content = {}

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
        cards_list = _build_cards_for_words(
            word_objects, current_user.id, activate_srs=True,
        )
    if not cards_list and isinstance(content, dict):
        cards_list = _build_display_cards_from_content(content)

    next_review_time = None
    if len(cards_list) == 0:
        if word_ids:
            earliest_card = (
                UserCardDirection.query
                .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
                .filter(
                    UserWord.user_id == current_user.id,
                    UserWord.word_id.in_(word_ids),
                    UserCardDirection.next_review.isnot(None),
                )
                .order_by(UserCardDirection.next_review.asc())
                .first()
            )
            if earliest_card and earliest_card.next_review:
                now_naive = datetime.now(UTC).replace(tzinfo=None)
                time_diff = earliest_card.next_review - now_naive
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
        # Используем именованный роут — даёт каноничный
        # /learn/<level>/module-<N>/ вместо легаси-якоря /learn/<level>/#module-N.
        # Якорная версия осталась с тех времён, когда уровень-страница
        # была одной длинной лентой со скроллом до anchor'а; сейчас у
        # каждого модуля своя страница.
        back_url = url_for(
            'learn.learn_by_module',
            level_code=lesson.module.level.code.lower(),
            module_number=lesson.module.number,
        )
    else:
        back_url = '/learn/'

    # Восстановление celebration на reload завершённого урока — те же
    # цифры, что показывали в финале первый раз, плюс актуальный
    # total_xp/level (могли вырасти после других уроков).
    is_completed = bool(progress and progress.status == 'completed')
    completed_stats = None
    if is_completed and isinstance(progress.data, dict) and progress.data:
        from app.achievements.models import UserStatistics
        from app.achievements.xp_service import get_level_info

        ustats = UserStatistics.query.filter_by(user_id=current_user.id).first()
        total_xp = (ustats.total_xp if ustats else 0) or 0
        completed_stats = {
            'cards_studied': progress.data.get('cards_studied', 0),
            'correct': progress.data.get('correct', 0),
            'accuracy': progress.data.get('accuracy', progress.score or 0),
            'total_xp': total_xp,
            'level': get_level_info(total_xp).current_level,
        }

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
        fc_lesson_mode=True,
        fc_is_completed=is_completed,
        fc_completed_stats=completed_stats,
        fc_retry_lesson_url=url_for('learn.lesson_by_id', lesson_id=lesson.id) + '?reset=true',
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
    content = {}

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
        cards_list = _build_cards_for_words(
            word_objects, current_user.id, activate_srs=True,
        )
    if not cards_list and isinstance(content, dict):
        cards_list = _build_display_cards_from_content(content)

    next_review_time = None
    if len(cards_list) == 0:
        if word_ids:
            earliest_card = (
                UserCardDirection.query
                .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
                .filter(
                    UserWord.user_id == current_user.id,
                    UserWord.word_id.in_(word_ids),
                    UserCardDirection.next_review.isnot(None),
                )
                .order_by(UserCardDirection.next_review.asc())
                .first()
            )
            if earliest_card and earliest_card.next_review:
                now_naive = datetime.now(UTC).replace(tzinfo=None)
                time_diff = earliest_card.next_review - now_naive
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
        # Используем именованный роут — даёт каноничный
        # /learn/<level>/module-<N>/ вместо легаси-якоря /learn/<level>/#module-N.
        # Якорная версия осталась с тех времён, когда уровень-страница
        # была одной длинной лентой со скроллом до anchor'а; сейчас у
        # каждого модуля своя страница.
        back_url = url_for(
            'learn.learn_by_module',
            level_code=lesson.module.level.code.lower(),
            module_number=lesson.module.number,
        )
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
        fc_lesson_mode=True,
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

        newly_completed = False
        if cards_studied > 0:
            newly_completed = progress.status != 'completed'
            progress.status = 'completed'
            progress.score = round(accuracy, 2)
            progress.completed_at = datetime.now(UTC)
            correct_for_data = int(round(cards_studied * (accuracy / 100)))
            # Сохраняем stats в progress.data — на повторном открытии урока
            # роут читает их и показывает celebration без перепрохождения
            # карточек (read-only re-view). Точно как у других уроков
            # (audio_fill_blank/shadow_reading/dictation/listening_immersion).
            progress.data = {
                'cards_studied': int(cards_studied),
                'correct': correct_for_data,
                'accuracy': float(accuracy),
            }
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(progress, 'data')

        db.session.commit()

        xp_award = None
        if newly_completed:
            try:
                from app.daily_plan.linear.xp import (
                    maybe_award_curriculum_xp,
                    maybe_award_linear_perfect_day,
                )
                xp_award = maybe_award_curriculum_xp(
                    current_user.id, lesson, db_session=db, score=accuracy,
                )
                if xp_award is not None:
                    maybe_award_linear_perfect_day(current_user.id, db_session=db)
                    db.session.commit()
            except Exception:
                logger.warning(
                    "linear_xp: card-lesson award failed user=%s lesson=%s",
                    current_user.id, lesson.id, exc_info=True,
                )
                db.session.rollback()

        from app.achievements.models import UserStatistics
        from app.achievements.xp_service import get_level_info

        stats = UserStatistics.query.filter_by(user_id=current_user.id).first()
        total_xp = (stats.total_xp if stats else 0) or 0
        level = get_level_info(total_xp).current_level

        correct = int(round(cards_studied * (accuracy / 100))) if cards_studied > 0 else 0
        incorrect = max(int(cards_studied) - correct, 0)

        response_data = {
            'success': True,
            'cards_studied': cards_studied,
            'accuracy': accuracy,
            'stats': {
                'words_studied': cards_studied,
                'correct': correct,
                'incorrect': incorrect,
                'percentage': accuracy,
            },
            'xp_earned': xp_award.xp_awarded if xp_award else 0,
            'total_xp': total_xp,
            'level': level,
        }

        # Attach refreshed daily_plan_ctx so the flashcard session can
        # update completion CTAs (or trigger the day-secured dashboard
        # redirect) right after the SRS session is committed.
        try:
            from app.daily_plan.linear.lesson_context import build_lesson_context
            dp_ctx = build_lesson_context(
                current_user.id, db, current_lesson_id=lesson_id
            )
            response_data['daily_plan_ctx'] = dp_ctx.to_dict()
        except Exception as ctx_err:
            logger.warning(
                "daily_plan_ctx attach failed (card-srs) user=%s lesson=%s: %s",
                current_user.id, lesson_id, ctx_err,
            )

        return jsonify(response_data)

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
@require_lesson_access
def get_next_review_time(lesson_id):
    """Get next review time for lesson"""
    try:
        Lessons.query.get_or_404(lesson_id)

        session_data = get_card_session_for_lesson(lesson_id, current_user.id)

        return jsonify({
            'next_review_time': session_data.get('next_review_time', 'Нет запланированных повторений')
        })

    except Exception as e:
        logger.error(f"Error getting next review time: {str(e)}")
        return jsonify({'next_review_time': 'Ошибка получения данных'}), 500
