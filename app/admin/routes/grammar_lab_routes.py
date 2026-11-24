# app/admin/routes/grammar_lab_routes.py

"""
Grammar Lab Admin Routes

Маршруты сгруппированы по доменам через `# region`-комментарии:

* TOPICS — CRUD по `GrammarTopic` (index, list, create, edit, delete).
* EXERCISES — CRUD по `GrammarExercise` (create/edit/delete).
* IMPORT — массовые операции импорта тем из curriculum-модулей и упражнений
  из сгенерированных JSON-файлов.
* API — read-only JSON-эндпоинты для админ-инструментов и автотестов.

Cascade-deletion упражнений (lapses/attempts/SRS-rows) обеспечивается
миграцией `20260425_grammar_exercise_cascade` (PostgreSQL) и
`ondelete='CASCADE'` в `GrammarExercise`, `UserGrammarExercise`,
`GrammarAttempt`. Не дублируем ручные `delete()` по дочерним таблицам.
"""
import json
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.admin.audit import log_admin_action
from app.admin.services.grammar_exercise_import import (
    JSON_SOURCE,
    MODULE_SOURCE,
    apply_replacement,
    guided_topic,
    lock_topics,
    plan_replacement,
    prepare_exercise,
    prepare_json_batch,
)
from app.admin.services.guided_topic_guard import managed_topic_editor
from app.admin.utils.decorators import admin_required
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db

grammar_lab_bp = Blueprint('grammar_lab_admin', __name__)
logger = logging.getLogger(__name__)

ALLOWED_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')
GRAMMAR_IMPORT_QUIZ_TYPES = (
    'quiz',
    'ordering_quiz',
    'translation_quiz',
    'listening_quiz',
    'dialogue_completion_quiz',
    'listening_immersion_quiz',
)


def _grammar_topic_payload(content: dict | None, lesson_title: str = '') -> tuple[str, dict]:
    """Normalize grammar lesson content from legacy and rich curriculum imports."""
    if not isinstance(content, dict):
        content = {}

    grammar_explanation = content.get('grammar_explanation') or {}
    if not isinstance(grammar_explanation, dict):
        grammar_explanation = {}

    rich_source = grammar_explanation if grammar_explanation else content
    title = (
        rich_source.get('title')
        or content.get('title')
        or lesson_title
        or content.get('rule')
        or ''
    )
    payload = {
        'introduction': (
            rich_source.get('introduction')
            or content.get('description')
            or content.get('content')
            or ''
        ),
        'sections': rich_source.get('sections') or content.get('sections') or [],
        'important_notes': (
            rich_source.get('important_notes')
            or content.get('important_notes')
            or []
        ),
        'summary': rich_source.get('summary') or content.get('summary') or {},
    }
    if content.get('rule'):
        payload['rule'] = content['rule']
    if content.get('examples'):
        payload['examples'] = content['examples']
    if rich_source.get('tldr'):
        payload['tldr'] = rich_source['tldr']
    return title.strip(), payload


def _first_present(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return None


def _coerce_answer(value):
    if isinstance(value, list):
        return value[0] if value else ''
    return value


def _module_exercise_content(ex: dict, *, strict: bool = False) -> tuple[str, dict] | tuple[None, None]:
    if not isinstance(ex, dict):
        return None, None

    raw_type = ex.get('type') or ex.get('exercise_type') or 'fill_blank'
    # Audio-dependent types are intentionally skipped: grammar_lab's
    # practice UI has no audio playback, so a ``listening_choice`` like
    # {audio: "...", question: "Что означает эта фраза?", options: [...]}
    # rendered there would show just the question with no way to hear
    # the source — user can't answer. Prior to this guard such items
    # fell through to ``fill_blank`` (the unrecognised-type default),
    # producing exercises with no source phrase / no playable audio.
    _AUDIO_TYPES = {'listening_choice', 'listening', 'audio_choice', 'audio_fill_blank', 'dictation'}
    if raw_type in _AUDIO_TYPES:
        return None, None
    type_mapping = {
        'fill_blank': 'fill_blank',
        'fill_in_blank': 'fill_blank',
        'multiple_choice': 'multiple_choice',
        'true_false': 'true_false',
        'matching': 'matching',
        'match': 'matching',
        'transformation': 'transformation',
        'error_correction': 'error_correction',
        'sentence_builder': 'reorder',
        'ordering': 'reorder',
        'reorder': 'reorder',
        'translation': 'translation',
    }
    mapped_type = type_mapping.get(raw_type, 'fill_blank')

    question = _first_present(
        ex.get('question'),
        ex.get('text'),
        ex.get('prompt'),
        ex.get('instruction'),
        ex.get('sentence'),
        ex.get('incorrect_sentence'),
    ) or ''
    correct_answer = _coerce_answer(_first_present(
        ex.get('correct'),
        ex.get('correct_answer'),
        ex.get('answer'),
        ex.get('correct_sentence'),
        ex.get('target'),
    ))
    exercise_content = {
        'question': question,
        'correct_answer': correct_answer,
        'explanation': ex.get('explanation', ''),
        'source': 'module_import',
    }

    if mapped_type == 'fill_blank':
        exercise_content['options'] = ex.get('options', [])
    elif mapped_type == 'multiple_choice':
        options = ex.get('options', [])
        exercise_content['options'] = options
        correct_value = _first_present(
            ex.get('correct'),
            ex.get('correct_answer'),
            ex.get('answer'),
            ex.get('correct_index'),
        )
        if isinstance(correct_value, str) and correct_value in options:
            exercise_content['correct_answer'] = options.index(correct_value)
        elif type(correct_value) is int and 0 <= correct_value < len(options):
            exercise_content['correct_answer'] = correct_value
        elif strict:
            raise ValueError('Нужен действующий ключ для вопроса на выбор ответа.')
        else:
            exercise_content['correct_answer'] = 0
    elif mapped_type == 'matching':
        exercise_content['pairs'] = ex.get('pairs', [])
    elif mapped_type == 'reorder':
        exercise_content['words'] = ex.get('words', [])
        correct_order = ex.get('correct_order')
        if isinstance(correct_order, list):
            exercise_content['correct_answer'] = ' '.join(str(word) for word in correct_order)
        else:
            exercise_content['correct_answer'] = _coerce_answer(_first_present(
                ex.get('correct'),
                ex.get('correct_answer'),
                ex.get('answer'),
            )) or ''
    elif mapped_type == 'true_false':
        exercise_content['statement'] = question
        exercise_content['correct_answer'] = _first_present(
            ex.get('correct'),
            ex.get('correct_answer'),
            ex.get('answer'),
            False,
        )
    elif mapped_type == 'translation':
        exercise_content['acceptable_answers'] = (
            ex.get('acceptable_answers')
            or ex.get('alternative_answers')
            or []
        )
        if 'Переведите на английский:' in question:
            sentence = question.replace('Переведите на английский:', '').strip()
        else:
            sentence = question
        exercise_content['sentence'] = sentence
    elif mapped_type == 'error_correction':
        exercise_content['sentence'] = _first_present(
            ex.get('incorrect_sentence'),
            ex.get('sentence'),
            question,
        ) or ''

    # Skip anything that wouldn't render as an answerable exercise. Unknown
    # module types (e.g. dialogue_completion) fall through to ``fill_blank``
    # above but carry no blank / source phrase, producing an empty input with
    # nothing to do. Mirrors the client-side ``isRenderable`` guard so the two
    # stay in sync. A complete import retires excluded source-owned rows.
    if not _module_content_is_renderable(mapped_type, exercise_content):
        if strict and raw_type in type_mapping:
            raise ValueError('Для упражнения не хватает текста или вариантов.')
        return None, None

    return mapped_type, exercise_content


def _module_content_is_renderable(mapped_type: str, content: dict) -> bool:
    """Return True when ``content`` has what its type needs to be answered."""
    def _txt(value) -> str:
        return str(value).strip() if value is not None else ''

    if mapped_type == 'reorder':
        return bool(content.get('words'))
    if mapped_type == 'multiple_choice':
        return len(content.get('options') or []) >= 2
    if mapped_type == 'matching':
        return bool(content.get('pairs'))
    if mapped_type == 'true_false':
        return bool(_txt(content.get('statement')) or _txt(content.get('question')))
    if mapped_type == 'error_correction':
        return bool(_txt(content.get('sentence')) or _txt(content.get('question')))
    if mapped_type == 'fill_blank':
        # Needs a blank to fill (question with ___) or an explicit source phrase.
        return '___' in _txt(content.get('question')) or bool(_txt(content.get('sentence')))
    # translation / transformation / anything else: need a non-empty prompt.
    return bool(_txt(content.get('question')) or _txt(content.get('sentence')))


def _exercise_list(value: object, *, strict: bool) -> list[dict]:
    if not isinstance(value, list):
        if strict:
            raise ValueError('Упражнения урока должны быть списком.')
        return []
    if strict and any(not isinstance(item, dict) for item in value):
        raise ValueError('Список упражнений содержит строку, которая не является объектом.')
    return [item for item in value if isinstance(item, dict)]


def _lesson_exercises(content: dict | None, *, strict: bool = False) -> list[dict]:
    if not isinstance(content, dict):
        if strict and content is not None:
            raise ValueError('Содержимое урока должно быть объектом.')
        return []

    for key in ('exercises', 'questions', 'items', 'tasks'):
        value = content.get(key)
        if isinstance(value, list) or (strict and value is not None):
            return _exercise_list(value, strict=strict)

    sections = content.get('test_sections')
    if strict and sections is not None and not isinstance(sections, list):
        raise ValueError('Разделы теста должны быть списком.')
    if isinstance(sections, list):
        exercises = []
        for section in sections:
            if not isinstance(section, dict):
                if strict:
                    raise ValueError('Раздел теста должен быть объектом.')
                continue
            for key in ('exercises', 'questions', 'items', 'tasks'):
                value = section.get(key)
                if isinstance(value, list) or (strict and value is not None):
                    exercises.extend(_exercise_list(value, strict=strict))
        return exercises

    return []


def _module_grammar_exercises(module_id: int, grammar_content: dict | None, *, strict: bool = False) -> list[dict]:
    from app.curriculum.models import Lessons

    exercises = list(_lesson_exercises(grammar_content, strict=strict))
    quiz_lessons = Lessons.query.filter(
        Lessons.module_id == module_id,
        Lessons.type.in_(GRAMMAR_IMPORT_QUIZ_TYPES),
    ).order_by(Lessons.number, Lessons.id).all()
    for quiz_lesson in quiz_lessons:
        exercises.extend(_lesson_exercises(quiz_lesson.content, strict=strict))
    return exercises


# region TOPICS ===============================================================

@grammar_lab_bp.route('/grammar-lab')
@admin_required
def grammar_lab_index():
    """Grammar Lab admin dashboard"""
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()

    # Stats
    stats = {
        'total_topics': len(topics),
        'total_exercises': GrammarExercise.query.count(),
        'by_level': {}
    }

    for level in ['A1', 'A2', 'B1', 'B2', 'C1']:
        count = sum(1 for t in topics if t.level == level)
        stats['by_level'][level] = count

    return render_template(
        'admin/grammar_lab/index.html',
        topics=topics,
        stats=stats
    )


@grammar_lab_bp.route('/grammar-lab/topics')
@admin_required
def topic_list():
    """List all grammar topics"""
    level = request.args.get('level')

    query = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order)
    if level:
        query = query.filter_by(level=level)

    topics = query.all()

    return render_template(
        'admin/grammar_lab/topic_list.html',
        topics=topics,
        current_level=level
    )


@grammar_lab_bp.route('/grammar-lab/topics/create', methods=['GET', 'POST'])
@admin_required
def create_topic():
    """Create a new grammar topic"""
    if request.method == 'POST':
        try:
            # Get form data
            slug = request.form.get('slug', '').strip()
            title = request.form.get('title', '').strip()
            title_ru = request.form.get('title_ru', '').strip()
            level = request.form.get('level', 'A1')
            if level not in ALLOWED_LEVELS:
                flash(f'Invalid level "{level}". Allowed: {", ".join(ALLOWED_LEVELS)}.', 'danger')
                return render_template('admin/grammar_lab/topic_form.html', topic=None)
            order = int(request.form.get('order', 0))
            estimated_time = int(request.form.get('estimated_time', 15))
            difficulty = int(request.form.get('difficulty', 1))

            # Parse content JSON
            content_json = request.form.get('content', '{}')
            try:
                content = json.loads(content_json) if content_json else {}
            except json.JSONDecodeError:
                content = {}

            # Create topic
            topic = GrammarTopic(
                slug=slug,
                title=title,
                title_ru=title_ru,
                level=level,
                order=order,
                content=content,
                estimated_time=estimated_time,
                difficulty=difficulty
            )
            db.session.add(topic)
            db.session.flush()
            log_admin_action(
                admin_id=current_user.id,
                action='grammar_topic.create',
                target_type='grammar_topic',
                target_id=topic.id,
            )
            db.session.commit()

            flash(f'Topic "{title}" created successfully!', 'success')
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic.id))

        except IntegrityError:
            db.session.rollback()
            logger.warning("Duplicate slug '%s' on grammar topic create", slug)
            flash(f'Error: slug "{slug}" is already taken. Choose a different slug.', 'danger')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating topic: {e}")
            flash(f'Error creating topic: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/topic_form.html', topic=None)


@grammar_lab_bp.route('/grammar-lab/topics/<int:topic_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_topic(topic_id):
    """Edit a grammar topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)

    if guided_editor := managed_topic_editor(topic.id):
        return guided_editor
    if request.method == 'POST':
        try:
            topic.slug = request.form.get('slug', topic.slug).strip()
            topic.title = request.form.get('title', topic.title).strip()
            topic.title_ru = request.form.get('title_ru', topic.title_ru).strip()
            submitted_level = request.form.get('level', topic.level)
            # Preserve legacy CEFR values (e.g. C2) when admin saves an unrelated
            # edit without touching the level dropdown.
            if submitted_level not in ALLOWED_LEVELS and submitted_level != topic.level:
                flash(f'Invalid level "{submitted_level}". Allowed: {", ".join(ALLOWED_LEVELS)}.', 'danger')
                return render_template('admin/grammar_lab/topic_form.html', topic=topic)
            topic.level = submitted_level
            topic.order = int(request.form.get('order', topic.order))
            topic.estimated_time = int(request.form.get('estimated_time', topic.estimated_time))
            topic.difficulty = int(request.form.get('difficulty', topic.difficulty))

            # Parse content JSON
            content_json = request.form.get('content', '{}')
            try:
                topic.content = json.loads(content_json) if content_json else {}
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in grammar topic content, keeping existing")

            log_admin_action(
                admin_id=current_user.id,
                action='grammar_topic.update',
                target_type='grammar_topic',
                target_id=topic_id,
            )
            db.session.commit()
            flash('Topic updated successfully!', 'success')

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating topic: {e}")
            flash(f'Error updating topic: {str(e)}', 'danger')

    # Get exercises for this topic
    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).order_by(
        GrammarExercise.order,
        GrammarExercise.difficulty
    ).all()

    return render_template(
        'admin/grammar_lab/topic_form.html',
        topic=topic,
        exercises=exercises
    )


@grammar_lab_bp.route('/grammar-lab/topics/<int:topic_id>/delete', methods=['POST'])
@admin_required
def delete_topic(topic_id):
    """Delete a grammar topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)
    if guided_editor := managed_topic_editor(topic_id):
        return guided_editor
    title = topic.title

    try:
        db.session.delete(topic)
        log_admin_action(
            admin_id=current_user.id,
            action='grammar_topic.delete',
            target_type='grammar_topic',
            target_id=topic_id,
        )
        db.session.commit()
        flash(f'Topic "{title}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(
            "Failed to delete grammar topic: admin_id=%s topic_id=%s error=%s",
            current_user.id, topic_id, e, exc_info=True,
        )
        flash(f'Error deleting topic: {str(e)}', 'danger')

    return redirect(url_for('grammar_lab_admin.topic_list'))


# endregion TOPICS

# region EXERCISES ============================================================

@grammar_lab_bp.route('/grammar-lab/topics/<int:topic_id>/exercises/create', methods=['GET', 'POST'])
@admin_required
def create_exercise(topic_id):
    """Create a new exercise for a topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)

    if guided_editor := managed_topic_editor(topic.id):
        return guided_editor
    if request.method == 'POST':
        try:
            exercise_type = request.form.get('exercise_type', 'fill_blank')
            order = int(request.form.get('order', 0))
            try:
                difficulty = int(request.form.get('difficulty', 1))
            except (ValueError, TypeError):
                difficulty = 1
            if not (1 <= difficulty <= 3):
                flash('Difficulty must be between 1 and 3.', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None), 400

            # Parse content JSON
            content_json = request.form.get('content', '{}')
            try:
                content = json.loads(content_json)
            except json.JSONDecodeError:
                flash('Invalid JSON in content field', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None)

            from app.grammar_lab.content_validator import validate_exercise_content
            try:
                validate_exercise_content(exercise_type, content)
            except ValueError as ve:
                flash(f'Invalid exercise content: {ve}', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None), 400

            exercise = GrammarExercise(
                topic_id=topic_id,
                exercise_type=exercise_type,
                content=content,
                difficulty=difficulty,
                order=order
            )
            db.session.add(exercise)
            db.session.flush()
            log_admin_action(
                admin_id=current_user.id,
                action='grammar_exercise.create',
                target_type='grammar_exercise',
                target_id=exercise.id,
            )
            db.session.commit()

            flash('Exercise created successfully!', 'success')
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic_id))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating exercise: {e}")
            flash(f'Error creating exercise: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None)


@grammar_lab_bp.route('/grammar-lab/exercises/<int:exercise_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_exercise(exercise_id):
    """Edit an exercise"""
    from app.admin.routes.materials import materials_return_url

    exercise = GrammarExercise.query.get_or_404(exercise_id)
    topic = exercise.topic

    if guided_editor := managed_topic_editor(topic.id):
        return guided_editor
    if request.method == 'POST':
        try:
            exercise.exercise_type = request.form.get('exercise_type', exercise.exercise_type)
            exercise.order = int(request.form.get('order', exercise.order))
            try:
                new_difficulty = int(request.form.get('difficulty', exercise.difficulty))
            except (ValueError, TypeError):
                new_difficulty = exercise.difficulty
            if not (1 <= new_difficulty <= 3):
                flash('Difficulty must be between 1 and 3.', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise), 400
            exercise.difficulty = new_difficulty

            content_json = request.form.get('content', '{}')
            try:
                exercise.content = json.loads(content_json)
            except json.JSONDecodeError:
                flash('Invalid JSON in content field', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise)

            from app.grammar_lab.content_validator import validate_exercise_content
            try:
                validate_exercise_content(exercise.exercise_type, exercise.content)
            except ValueError as ve:
                db.session.rollback()
                flash(f'Invalid exercise content: {ve}', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise), 400

            log_admin_action(
                admin_id=current_user.id,
                action='grammar_exercise.update',
                target_type='grammar_exercise',
                target_id=exercise_id,
            )
            db.session.commit()
            flash('Exercise updated successfully!', 'success')
            return redirect(materials_return_url() or url_for('grammar_lab_admin.edit_topic', topic_id=topic.id))

        except Exception as e:
            db.session.rollback()
            logger.error(
                "Failed to update grammar exercise: admin_id=%s exercise_id=%s error=%s",
                current_user.id, exercise_id, e, exc_info=True,
            )
            flash(f'Error updating exercise: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise)


@grammar_lab_bp.route('/grammar-lab/exercises/<int:exercise_id>/delete', methods=['POST'])
@admin_required
def delete_exercise(exercise_id):
    """Delete an exercise"""
    exercise = GrammarExercise.query.get_or_404(exercise_id)
    topic_id = exercise.topic_id

    if guided_editor := managed_topic_editor(topic_id):
        return guided_editor
    try:
        db.session.delete(exercise)
        log_admin_action(
            current_user.id, 'grammar_exercise.delete',
            target_type='grammar_exercise', target_id=exercise_id,
        )
        db.session.commit()
        flash('Exercise deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(
            "Failed to delete grammar exercise: admin_id=%s exercise_id=%s error=%s",
            current_user.id, exercise_id, e, exc_info=True,
        )
        flash(f'Error deleting exercise: {str(e)}', 'danger')

    return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic_id))


# endregion EXERCISES

# region IMPORT ===============================================================

@grammar_lab_bp.route('/grammar-lab/import-from-modules', methods=['GET', 'POST'])
@admin_required
def import_from_modules():
    """Import grammar topics from curriculum modules (from database)"""
    from app.curriculum.models import CEFRLevel, Lessons, Module

    if request.method == 'POST':
        from app.curriculum.models import LessonProgress
        from app.grammar_lab.models import UserGrammarTopicStatus

        try:
            # Serialize imports even for modules whose topics do not exist yet.
            modules = Module.query.order_by(Module.id).with_for_update().all()
            targets = []
            topic_ids: set[int] = set()
            for module in modules:
                grammar_lesson = Lessons.query.filter_by(module_id=module.id, type='grammar').order_by(
                    Lessons.number, Lessons.id,
                ).first()
                if not grammar_lesson:
                    continue
                level_code = module.level.code
                slug = f'{level_code.lower()}-{module.number}'
                topic = (db.session.get(GrammarTopic, grammar_lesson.grammar_topic_id)
                         if grammar_lesson.grammar_topic_id else None)
                if topic is None:
                    topic = GrammarTopic.query.filter_by(slug=slug).one_or_none()
                if topic is not None:
                    if topic.id in topic_ids:
                        raise ValueError(f'Несколько модулей ссылаются на тему «{topic.title}».')
                    topic_ids.add(topic.id)
                targets.append((module, grammar_lesson, slug, topic.id if topic else None))

            topics = lock_topics(topic_ids)
            plans = []
            for module, lesson, slug, topic_id in targets:
                topic = topics.get(topic_id)
                if topic is not None and guided_topic(topic):
                    continue
                if lesson.content is not None and not isinstance(lesson.content, dict):
                    raise ValueError(f'Модуль {slug}: содержимое урока должно быть объектом.')
                title, topic_content = _grammar_topic_payload(lesson.content, lesson.title)
                if not title:
                    continue
                topic_content['source_module'] = module.number
                desired = []
                for index, row in enumerate(_module_grammar_exercises(module.id, lesson.content, strict=True)):
                    try:
                        mapped_type, content = _module_exercise_content(row, strict=True)
                        if mapped_type:
                            desired.append(prepare_exercise(mapped_type, content, source=MODULE_SOURCE, order=index))
                    except (TypeError, ValueError) as error:
                        raise ValueError(f'Модуль {slug}, упражнение {index + 1}: {error}') from error
                plan = plan_replacement(topic, MODULE_SOURCE, desired)
                plans.append((module, lesson, slug, topic, title, topic_content, plan))

            created = updated = synced = added = kept = retired = 0
            for module, lesson, slug, topic, title, content, plan in plans:
                if topic is None:
                    topic = GrammarTopic(id=module.id, estimated_time=15, difficulty=1)
                    db.session.add(topic)
                    created += 1
                else:
                    updated += 1
                topic.slug = slug
                topic.title = topic.title_ru = title
                topic.level = module.level.code
                topic.order = module.number
                topic.content = content
                db.session.flush()
                lesson.grammar_topic_id = topic.id
                apply_replacement(topic, plan)
                added += len(plan.additions)
                kept += plan.retained
                retired += len(plan.retirements)
                completed = LessonProgress.query.filter_by(lesson_id=lesson.id, status='completed').all()
                for progress in completed:
                    status = UserGrammarTopicStatus.get_or_create(progress.user_id, topic.id)
                    synced += int(bool(status.transition_to('theory_completed')))

            if plans:
                log_admin_action(current_user.id, 'grammar_topic.import_from_modules', target_type='grammar_topic',
                                 required=True)
            db.session.commit()
            flash(
                f'Тем создано: {created}, обновлено: {updated}. Упражнений добавлено: {added}, '
                f'сохранено: {kept}, снято: {retired}. Синхронизировано прогрессов: {synced}.',
                'success',
            )
        except ValueError as error:
            db.session.rollback()
            flash(f'Импорт отменён: {error}', 'danger')
        except Exception:
            db.session.rollback()
            logger.exception('Grammar Lab module import failed')
            flash('Импорт из модулей отменён. Изменения не сохранены.', 'danger')

        return redirect(url_for('grammar_lab_admin.grammar_lab_index'))

    # GET - show preview
    modules_with_grammar = []
    modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()

    for module in modules:
        level_code = module.level.code if module.level else 'A1'

        # Find grammar lesson
        grammar_lesson = Lessons.query.filter_by(
            module_id=module.id,
            type='grammar'
        ).first()

        if not grammar_lesson:
            continue

        content = grammar_lesson.content or {}
        title, _topic_content = _grammar_topic_payload(content, grammar_lesson.title)

        if not title:
            continue

        # Check if exists
        slug = f"{level_code.lower()}-{module.number}"
        exists = bool(
            (grammar_lesson.grammar_topic_id and GrammarTopic.query.get(grammar_lesson.grammar_topic_id))
            or GrammarTopic.query.filter_by(slug=slug).first()
        )

        exercise_count = len(_module_grammar_exercises(module.id, content))

        modules_with_grammar.append({
            'module_id': module.number,
            'module_title': module.title,
            'level': level_code,
            'grammar_title': title,
            'exists': exists,
            'exercise_count': exercise_count
        })

    return render_template(
        'admin/grammar_lab/import_preview.html',
        modules_with_grammar=modules_with_grammar
    )


@grammar_lab_bp.route('/grammar-lab/import-exercises-json', methods=['GET', 'POST'])
@admin_required
def import_exercises_json():
    """Import extra exercises from one or more generated JSON files."""
    if request.method == 'POST':
        files = [f for f in request.files.getlist('json_files') if f and f.filename]
        if not files:
            legacy_file = request.files.get('json_file')
            if legacy_file and legacy_file.filename:
                files = [legacy_file]

        if not files:
            flash('Файл не выбран', 'danger')
            return redirect(request.url)

        try:
            batch = prepare_json_batch(files)
            topics = lock_topics(batch)
            plans = {}
            for topic_id, (slug, desired) in sorted(batch.items()):
                topic = topics[topic_id]
                if topic.slug != slug or guided_topic(topic):
                    raise ValueError(f'Тема «{slug}» изменилась. Повторите загрузку.')
                plans[topic_id] = plan_replacement(topic, JSON_SOURCE, desired)
            for topic_id, plan in plans.items():
                apply_replacement(topics[topic_id], plan)
                log_admin_action(current_user.id, 'grammar_exercise.import_json',
                                 target_type='grammar_topic', target_id=topic_id, required=True)
            db.session.commit()
        except ValueError as error:
            db.session.rollback()
            flash(f'Импорт отменён: {error}', 'danger')
            return redirect(request.url)
        except Exception:
            db.session.rollback()
            logger.exception('Grammar Lab JSON import failed')
            flash('Импорт JSON отменён. Изменения не сохранены.', 'danger')
            return redirect(request.url)

        for topic_id, plan in plans.items():
            flash(f'Тема «{topics[topic_id].title}»: добавлено {len(plan.additions)}, '
                  f'сохранено {plan.retained}, снято {len(plan.retirements)}.', 'success')
        return redirect(url_for('grammar_lab_admin.grammar_lab_index'))

    # GET — show upload form
    return render_template('admin/grammar_lab/import_exercises_json.html')


# endregion IMPORT

# region API ==================================================================

@grammar_lab_bp.route('/grammar-lab/api/topics', methods=['GET'])
@admin_required
def api_topics():
    """Get all topics as JSON"""
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()
    return jsonify([t.to_dict() for t in topics])


@grammar_lab_bp.route('/grammar-lab/api/topic/<int:topic_id>/exercises', methods=['GET'])
@admin_required
def api_topic_exercises(topic_id):
    """Get exercises for a topic"""
    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).order_by(
        GrammarExercise.order
    ).all()
    return jsonify([e.to_dict() for e in exercises])

# endregion API
