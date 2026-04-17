import logging
import re

from flask import url_for
from flask_login import current_user
from sqlalchemy import case
from sqlalchemy.orm import joinedload

from app.curriculum.book_courses import (
    BookCourse, BookCourseEnrollment, BookCourseModule,
)
from app.curriculum.daily_lessons import DailyLesson, SliceVocabulary
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.utils.db import db

logger = logging.getLogger(__name__)

_LESSON_TYPE_ORDER = case(
    (DailyLesson.lesson_type == 'vocabulary', 0),
    (DailyLesson.lesson_type == 'context_review', 1),
    (DailyLesson.lesson_type == 'reading', 9),
    else_=5,
)
LESSON_ORDER = (DailyLesson.day_number, _LESSON_TYPE_ORDER, DailyLesson.id)

LESSON_TYPE_TRANSLATIONS = {
    'vocabulary':        {'ru': 'Словарь',              'en': 'Vocabulary'},
    'reading':           {'ru': 'Чтение',               'en': 'Reading'},
    'language_focus':    {'ru': 'Грамматика',           'en': 'Grammar'},
    'grammar_focus':     {'ru': 'Грамматика',           'en': 'Grammar'},
    'comprehension_mcq': {'ru': 'Тест на понимание',    'en': 'Reading Quiz'},
    'phrase_cloze':      {'ru': 'Заполнение пропусков', 'en': 'Cloze Practice'},
    'cloze_practice':    {'ru': 'Заполнение пропусков', 'en': 'Cloze Practice'},
    'context_review':    {'ru': 'Фразы в контексте',    'en': 'Key Phrases in Context'},
    'vocabulary_review': {'ru': 'Повторение слов',      'en': 'Card Review'},
    'guided_retelling':  {'ru': 'Пересказ',             'en': 'Retelling'},
    'summary_writing':   {'ru': 'Краткий пересказ',     'en': 'Summary'},
    'module_test':       {'ru': 'Тест модуля',          'en': 'Module Test'},
    'anki_session':      {'ru': 'Повторение слов',      'en': 'Card Review'},
    'reading_part1':       {'ru': 'Чтение (часть 1)',     'en': 'Reading (Part 1)'},
    'reading_part2':       {'ru': 'Чтение (часть 2)',     'en': 'Reading (Part 2)'},
    'vocabulary_practice': {'ru': 'Практика словаря',     'en': 'Vocabulary Practice'},
    'discussion':          {'ru': 'Обсуждение',           'en': 'Discussion'},
    'mixed_practice':      {'ru': 'Смешанная практика',   'en': 'Mixed Practice'},
    'reading_passage':   {'ru': 'Чтение',            'en': 'Reading'},
    'reading_assignment':{'ru': 'Чтение',            'en': 'Reading'},
    'reading_mcq':       {'ru': 'Тест по чтению',    'en': 'Reading Quiz'},
    'match_headings':    {'ru': 'Заголовки',          'en': 'Match Headings'},
    'open_cloze':        {'ru': 'Пропуски',           'en': 'Open Cloze'},
    'word_formation':    {'ru': 'Словообразование',   'en': 'Word Formation'},
    'keyword_transform': {'ru': 'Трансформации',      'en': 'Key Word Transform'},
    'grammar_sheet':     {'ru': 'Грамматика',         'en': 'Grammar'},
    'grammar':           {'ru': 'Грамматика',         'en': 'Grammar'},
    'final_test':        {'ru': 'Итоговый тест',      'en': 'Final Test'},
    'srs':               {'ru': 'Повторение слов',    'en': 'Card Review'},
}


def get_ui_lang(course_level: str) -> str:
    level = (course_level or "").upper()
    if level in ("A1", "A2"):
        return "ru"
    if level in ("C1", "C2"):
        return "en"
    return "mixed"


def get_lesson_type_display(lesson_type: str, ui_lang: str = 'ru') -> str:
    lang = 'ru' if ui_lang in ('ru', 'mixed') else 'en'
    entry = LESSON_TYPE_TRANSLATIONS.get(lesson_type)
    if entry:
        return entry.get(lang, entry.get('ru', lesson_type))
    return lesson_type.replace('_', ' ').title()


def truncate_context(text: str, max_sentences: int = 1) -> str:
    if not text:
        return ''
    parts = re.split(r'\.\s+(?=[A-Z])', text.strip())
    if len(parts) <= max_sentences:
        return text
    result = '. '.join(parts[:max_sentences])
    if not result.endswith('.'):
        result += '.'
    return result


def _parse_lesson_scaffold(raw_annotations):
    if raw_annotations is None:
        return {
            'annotations': None, 'objectives': None, 'before_reading': None,
            'reflection': None, 'self_check': None, 'can_do': None,
        }
    if isinstance(raw_annotations, list):
        return {
            'annotations': raw_annotations, 'objectives': None, 'before_reading': None,
            'reflection': None, 'self_check': None, 'can_do': None,
        }
    return {
        'annotations': raw_annotations.get('annotations'),
        'objectives': raw_annotations.get('objectives'),
        'before_reading': raw_annotations.get('before_reading'),
        'reflection': raw_annotations.get('reflection'),
        'self_check': raw_annotations.get('self_check'),
        'can_do': raw_annotations.get('can_do'),
    }


def get_course_by_slug_or_id(course_identifier):
    try:
        course_id = int(course_identifier)
        return BookCourse.query.get_or_404(course_id)
    except (ValueError, TypeError):
        return BookCourse.query.filter_by(slug=course_identifier).first_or_404()


def get_pretty_lesson_url(course, module, lesson_index):
    if course.slug:
        return url_for('book_courses.view_lesson_by_slug',
                      course_slug=course.slug,
                      module_number=module.module_number,
                      lesson_number=lesson_index)
    else:
        return url_for('book_courses.view_lesson',
                      course_id=course.id,
                      module_id=module.id,
                      lesson_number=lesson_index)


def _build_linked_topics_and_return_url(lf: dict, course, module, next_lesson_url: str, has_next_lesson: bool):
    from app.grammar_lab.models import GrammarTopic, GrammarExercise

    linked_topics = []
    for tid in lf.get('linked_grammar_topic_ids', []):
        if isinstance(tid, str):
            t = GrammarTopic.query.filter_by(slug=tid).first()
        else:
            t = GrammarTopic.query.get(tid)
        if t:
            ex_count = GrammarExercise.query.filter_by(topic_id=t.id).count()
            linked_topics.append({
                'id': t.id, 'title': t.title, 'title_ru': t.title_ru,
                'level': t.level, 'exercise_count': ex_count, 'content': t.content,
            })

    if has_next_lesson and next_lesson_url:
        grammar_return_url = next_lesson_url
    elif course.slug:
        grammar_return_url = url_for(
            'book_courses.view_module_by_slug',
            course_slug=course.slug, module_number=module.module_number
        )
    else:
        grammar_return_url = url_for(
            'book_courses.view_module',
            course_id=course.id, module_id=module.id
        )

    return linked_topics, grammar_return_url


def _build_vocabulary_fc_vars(
    vocabulary_data: list[dict],
    course: 'BookCourse',
    module: 'BookCourseModule',
    daily_lesson: 'DailyLesson | None',
    next_lesson_url: str | None,
    has_next_lesson: bool,
    is_review: bool = False,
) -> dict:
    fc_cards: list[dict] = []
    srs_session_key: str | None = None
    fc_nothing_to_study = False

    if daily_lesson and current_user.is_authenticated:
        try:
            enrollment = BookCourseEnrollment.query.filter_by(
                user_id=current_user.id, course_id=course.id
            ).first()
            if enrollment:
                srs = BookSRSIntegration()
                session_data = srs.create_srs_session_for_lesson(
                    user_id=current_user.id,
                    daily_lesson=daily_lesson,
                    enrollment=enrollment
                )
                srs_session_key = session_data.get('session_key')
                studied_today = session_data.get('studied_today', 0)
                for card in session_data.get('deck', []):
                    fc_cards.append({
                        'word_id': card.get('word_id'),
                        'card_id': card.get('card_id'),
                        'direction_id': None,
                        'direction': card.get('direction', 'eng-rus'),
                        'front': card.get('front', ''),
                        'back': card.get('back', ''),
                        'audio_url': card.get('audio_url'),
                        'example': card.get('examples', '') or '',
                        'example_translation': '',
                        'book_context': card.get('context'),
                        'status': card.get('phase', 'new'),
                        'is_new': card.get('new', True),
                        'word': card.get('lemma', card.get('front', '')),
                        'translation': card.get('translation', card.get('back', '')),
                        'unit_type': card.get('unit_type'),
                        'note': card.get('note'),
                    })
                if not fc_cards and studied_today > 0:
                    fc_nothing_to_study = True
        except Exception as e:
            logger.error(f"Error loading SRS session for vocabulary: {e}")

    if not fc_cards and not fc_nothing_to_study:
        for v in vocabulary_data:
            fc_cards.append({
                'word_id': v.get('id'),
                'card_id': None,
                'direction_id': None,
                'direction': 'eng-rus',
                'front': v.get('lemma', ''),
                'back': v.get('translation', ''),
                'audio_url': v.get('audio_url'),
                'example': v.get('example', ''),
                'example_translation': '',
                'book_context': v.get('context'),
                'status': 'new',
                'is_new': True,
                'word': v.get('lemma', ''),
                'translation': v.get('translation', ''),
                'unit_type': v.get('unit_type'),
                'note': v.get('note'),
            })

    if course.slug:
        back_url = url_for('book_courses.view_module_by_slug',
                           course_slug=course.slug,
                           module_number=module.module_number)
    else:
        back_url = url_for('book_courses.view_module',
                           course_id=course.id, module_id=module.id)

    mark_complete_url: str | None = None
    if daily_lesson:
        mark_complete_url = f'/curriculum/api/v1/lesson/{daily_lesson.id}/complete'

    title_suffix = 'Повторение слов' if is_review else 'Словарь'

    return {
        'fc_title': f"{course.title}: {title_suffix}",
        'fc_back_url': back_url,
        'fc_cards': fc_cards,
        'fc_grade_url': '/curriculum/api/v1/srs/grade',
        'fc_grade_payload': (
            '(function(card, rating, sessionId) {'
            ' return { card_id: card.card_id || card.word_id,'
            ' rating: rating,'
            ' session_key: '
            + (f'"{srs_session_key}"' if srs_session_key else '"book_vocab"')
            + ' };'
            '})'
        ),
        'fc_mark_complete_url': mark_complete_url,
        'fc_on_complete_url': next_lesson_url or back_url,
        'fc_on_complete_text': 'Следующий урок' if has_next_lesson else 'К модулю',
        'fc_session_id': srs_session_key,
        'fc_show_examples': True,
        'fc_show_audio': True,
        'fc_show_book_context': True,
        'fc_nothing_to_study': fc_nothing_to_study,
    }


def build_daily_lesson_dict(daily_lesson, course_level: str) -> dict:
    ui_lang = get_ui_lang(course_level)
    type_label = get_lesson_type_display(daily_lesson.lesson_type, ui_lang)
    if ui_lang == 'en':
        title = f'Day {daily_lesson.day_number}: {type_label}'
    else:
        title = f'День {daily_lesson.day_number}: {type_label}'
    return {
        'lesson_number': daily_lesson.day_number,
        'type': daily_lesson.lesson_type,
        'title': title,
        'slice_text': daily_lesson.slice_text,
        'word_count': daily_lesson.word_count,
        'task_id': daily_lesson.task_id,
        'daily_lesson_id': daily_lesson.id,
        'available_at': daily_lesson.available_at,
    }


def find_next_lesson_url(daily_lesson, module_id, course, module):
    all_lessons = DailyLesson.query.filter_by(
        book_course_module_id=module_id
    ).order_by(*LESSON_ORDER).all()

    for i, dl in enumerate(all_lessons):
        if dl.id == daily_lesson.id and i < len(all_lessons) - 1:
            next_daily_lesson = all_lessons[i + 1]
            next_position = i + 2
            if course.slug:
                next_url = url_for(
                    'book_courses.view_lesson_by_slug',
                    course_slug=course.slug,
                    module_number=module.module_number,
                    lesson_number=next_position
                )
            else:
                next_url = url_for(
                    'book_courses.view_lesson_by_id',
                    course_id=course.id,
                    module_id=module_id,
                    lesson_id=next_daily_lesson.id
                )
            return next_url, True
    return None, False


def load_vocabulary_data(daily_lesson, lesson, course_level: str, max_words: int = 7) -> list[dict]:
    vocabulary_data = []
    if daily_lesson:
        from app.curriculum.services.book_srs_integration import is_word_learned
        slice_vocab = SliceVocabulary.query.filter_by(
            daily_lesson_id=daily_lesson.id
        ).options(joinedload(SliceVocabulary.word)).order_by(
            SliceVocabulary.priority.desc(),
            SliceVocabulary.frequency_in_slice.desc()
        ).all()

        for sv in slice_vocab:
            if current_user.is_authenticated:
                if is_word_learned(current_user.id, sv.word_id):
                    continue
            word = sv.word
            context = truncate_context(sv.context_sentence or '', max_sentences=1)
            db_example = getattr(word, 'sentences', '') or ''
            db_example = db_example.replace('\\n', '\n').replace('<br>', '\n').replace('<br/>', '\n')

            vocab_item = {
                'id': word.id,
                'lemma': word.english_word,
                'translation': word.russian_word,
                'context': context,
                'example': db_example,
                'audio_url': f'/static/audio/pronunciation_en_{word.english_word.lower().replace(" ", "_")}.mp3',
                'has_audio': getattr(word, 'get_download', 0) == 1,
                'frequency': sv.frequency_in_slice,
                'part_of_speech': getattr(word, 'pos', 'unknown'),
                'level': getattr(word, 'level', None),
                'transcription': getattr(word, 'transcription', None),
            }
            vocabulary_data.append(vocab_item)
            if len(vocabulary_data) >= max_words:
                break
    else:
        task_id = lesson.get('task_id')
        if task_id:
            from app.books.models import Task
            task = Task.query.get(task_id)
            if task and task.payload:
                cards = task.payload.get('cards', [])
                for idx, card in enumerate(cards):
                    vocab_item = {
                        'id': idx + 1,
                        'lemma': card.get('front', ''),
                        'translation': card.get('back', {}).get('translation', ''),
                        'example': card.get('back', {}).get('examples', [''])[0] if card.get('back', {}).get('examples') else '',
                        'audio_url': card.get('audio_url', ''),
                        'frequency': card.get('back', {}).get('frequency', 0),
                    }
                    vocabulary_data.append(vocab_item)
                    if len(vocabulary_data) >= max_words:
                        break
    return vocabulary_data


def ensure_words_in_book_deck(user_id: int, course, vocabulary_data: list[dict]):
    from app.curriculum.services.book_srs_integration import get_or_create_book_course_deck
    from app.study.models import QuizDeckWord
    try:
        book_deck = get_or_create_book_course_deck(user_id, course)
        if book_deck and vocabulary_data:
            words_added = 0
            for vocab in vocabulary_data:
                word_id = vocab.get('id')
                if word_id:
                    existing = QuizDeckWord.query.filter_by(
                        deck_id=book_deck.id, word_id=word_id
                    ).first()
                    if not existing:
                        deck_word = QuizDeckWord(deck_id=book_deck.id, word_id=word_id)
                        db.session.add(deck_word)
                        words_added += 1
            if words_added > 0:
                logger.info(f"Added {words_added} words to deck {book_deck.id}")
        db.session.commit()
        return book_deck
    except Exception as e:
        logger.error(f"Error creating book deck: {str(e)}", exc_info=True)
        db.session.rollback()
        return None
