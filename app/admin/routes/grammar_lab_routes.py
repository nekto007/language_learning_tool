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
import re

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db

grammar_lab_bp = Blueprint('grammar_lab_admin', __name__)
logger = logging.getLogger(__name__)

ALLOWED_LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')


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


def _delete_module_imported_exercises(topic_id: int) -> int:
    """Delete exercises created by module import while preserving JSON extras."""
    deleted = 0
    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).all()
    for exercise in exercises:
        content = exercise.content if isinstance(exercise.content, dict) else {}
        if content.get('source') == 'json_import':
            continue
        db.session.delete(exercise)
        deleted += 1
    return deleted


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


def _module_exercise_content(ex: dict) -> tuple[str, dict] | tuple[None, None]:
    if not isinstance(ex, dict):
        return None, None

    raw_type = ex.get('type') or ex.get('exercise_type') or 'fill_blank'
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
        elif isinstance(correct_value, int):
            exercise_content['correct_answer'] = correct_value
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

    return mapped_type, exercise_content


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
    exercise = GrammarExercise.query.get_or_404(exercise_id)
    topic = exercise.topic

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
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic.id))

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
        imported = 0
        skipped = 0
        exercises_imported = 0
        total_synced = 0

        try:
            # Get all modules with their levels
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
                title, topic_content = _grammar_topic_payload(content, grammar_lesson.title)

                if not title:
                    continue

                # Generate slug: {level}-{number}
                slug = f"{level_code.lower()}-{module.number}"

                # Check if already exists: first by grammar_topic_id, then by slug
                existing = None
                if grammar_lesson.grammar_topic_id:
                    existing = GrammarTopic.query.get(grammar_lesson.grammar_topic_id)
                if not existing:
                    existing = GrammarTopic.query.filter_by(slug=slug).first()
                if existing:
                    # Update existing topic
                    topic = existing
                    topic.slug = slug
                    topic.title = title
                    topic.title_ru = title
                    topic.level = level_code
                    topic.order = module.number
                    topic_content['source_module'] = module.number
                    topic.content = topic_content
                    # Delete old module exercises to reimport (preserve JSON-imported)
                    _delete_module_imported_exercises(topic.id)
                    skipped += 1  # Count as updated (using skipped for "updated" count)
                else:
                    # Create new topic with id = module.id
                    topic_content['source_module'] = module.number
                    topic = GrammarTopic(
                        id=module.id,
                        slug=slug,
                        title=title,
                        title_ru=title,
                        level=level_code,
                        order=module.number,
                        content=topic_content,
                        estimated_time=15,
                        difficulty=1
                    )
                    db.session.add(topic)
                    db.session.flush()
                    imported += 1

                # Link source grammar lesson back to the topic
                grammar_lesson.grammar_topic_id = topic.id

                # Retroactive sync: if users already completed this lesson, update Grammar Lab status
                from app.curriculum.models import LessonProgress
                from app.grammar_lab.models import UserGrammarTopicStatus
                synced_count = 0
                completed_progresses = LessonProgress.query.filter_by(
                    lesson_id=grammar_lesson.id,
                    status='completed'
                ).all()
                if not completed_progresses:
                    # Try broader search - maybe status differs
                    all_progresses = LessonProgress.query.filter_by(
                        lesson_id=grammar_lesson.id
                    ).all()
                    logger.info(
                        f"Module {module.number}: lesson {grammar_lesson.id} has "
                        f"{len(all_progresses)} progress records, "
                        f"statuses: {[p.status for p in all_progresses]}"
                    )
                for progress in completed_progresses:
                    try:
                        topic_st = UserGrammarTopicStatus.get_or_create(progress.user_id, topic.id)
                        if topic_st.transition_to('theory_completed'):
                            synced_count += 1
                            logger.info(f"Synced user {progress.user_id} for topic {topic.id}")
                        else:
                            logger.info(
                                f"User {progress.user_id} topic {topic.id}: "
                                f"already status={topic_st.status}, skip"
                            )
                    except Exception as e:
                        logger.warning(f"Retroactive sync failed for user {progress.user_id}: {e}")
                total_synced += synced_count
                if synced_count > 0:
                    logger.info(f"Module {module.number}: synced {synced_count} users")

                # Упражнения могут быть сохранены прямо в grammar lesson после
                # curriculum import или вынесены в отдельные quiz lessons.
                exercises = list(content.get('exercises', []) if isinstance(content, dict) else [])
                quiz_lessons = Lessons.query.filter_by(
                    module_id=module.id,
                    type='quiz'
                ).all()
                for quiz_lesson in quiz_lessons:
                    quiz_content = quiz_lesson.content or {}
                    lesson_exercises = quiz_content.get('exercises', [])
                    exercises.extend(lesson_exercises)
                if exercises:

                    for i, ex in enumerate(exercises):
                        mapped_type, exercise_content = _module_exercise_content(ex)
                        if not mapped_type:
                            continue

                        from app.grammar_lab.content_validator import validate_exercise_content
                        try:
                            validate_exercise_content(mapped_type, exercise_content)
                        except ValueError as ve:
                            logger.warning(
                                'Skipping module grammar exercise: module_id=%s topic_id=%s type=%s error=%s',
                                module.id, topic.id, mapped_type, ve,
                            )
                            continue

                        exercise = GrammarExercise(
                            topic_id=topic.id,
                            exercise_type=mapped_type,
                            content=exercise_content,
                            difficulty=1,
                            order=i
                        )
                        db.session.add(exercise)
                        exercises_imported += 1

            if imported or skipped or exercises_imported:
                log_admin_action(
                    current_user.id,
                    'grammar_topic.import_from_modules',
                    target_type='grammar_topic',
                )
            db.session.commit()
            sync_msg = f', синхронизировано прогрессов: {total_synced}' if total_synced else ''
            flash(
                f'Создано: {imported} тем, обновлено: {skipped} тем, '
                f'упражнений: {exercises_imported}{sync_msg}',
                'success',
            )

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error importing grammar: {e}")
            flash(f'Ошибка импорта: {str(e)}', 'danger')

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

        # Упражнения могут быть сохранены прямо в grammar lesson или в quiz lessons.
        quiz_lessons = Lessons.query.filter_by(
            module_id=module.id,
            type='quiz'
        ).all()

        exercise_count = len(content.get('exercises', []) if isinstance(content, dict) else [])
        for quiz_lesson in quiz_lessons:
            quiz_content = quiz_lesson.content or {}
            lesson_exercises = quiz_content.get('exercises', [])
            exercise_count += len(lesson_exercises)

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


def _candidate_topic_slugs(data: dict, filename: str) -> list[str]:
    """Return possible GrammarTopic slugs for generated extra exercise files."""
    candidates = []

    level = str(data.get('level', '')).lower()
    module_id = data.get('module_id')
    if level and module_id:
        candidates.append(f'{level}-{module_id}')

    filename_match = re.search(
        r'grammar_extra_([a-z0-9]+)_(\d+)\.json$',
        filename,
        flags=re.IGNORECASE,
    )
    if filename_match:
        filename_level = filename_match.group(1).lower()
        filename_module_number = filename_match.group(2)
        candidates.append(f'{filename_level}-{filename_module_number}')

    return list(dict.fromkeys(candidates))


def _import_exercises_json_file(file, deleted_topic_ids: set[int]) -> tuple[bool, str]:
    """Import one generated Grammar Lab exercises JSON file.

    ``deleted_topic_ids`` is shared for one upload batch so multiple files for
    the same topic append within the batch instead of deleting each other.
    """
    filename = file.filename or 'unknown'

    if not filename.lower().endswith('.json'):
        return False, f'{filename}: допустимы только .json файлы'

    try:
        data = json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return False, f'{filename}: ошибка парсинга JSON: {e}'

    module_id = data.get('module_id')
    topic_slug_part = data.get('grammar_topic_slug', '')
    sessions = data.get('sessions', [])

    if not module_id or not topic_slug_part:
        return False, f'{filename}: JSON не содержит module_id или grammar_topic_slug'

    candidate_slugs = _candidate_topic_slugs(data, filename)
    topic = None
    matched_slug = None
    for candidate_slug in candidate_slugs:
        topic = GrammarTopic.query.filter_by(slug=candidate_slug).first()
        if topic:
            matched_slug = candidate_slug
            break

    if not topic:
        checked = ', '.join(f'"{slug}"' for slug in candidate_slugs) or 'нет'
        return (
            False,
            f'{filename}: тема не найдена. Проверены slug: {checked}. '
            'Сначала импортируйте темы из модулей.',
        )

    exercises_imported = 0
    deleted = 0
    deleted_in_this_file = False
    try:
        if topic.id not in deleted_topic_ids:
            deleted = GrammarExercise.query.filter(
                GrammarExercise.topic_id == topic.id,
                GrammarExercise.content['source'].astext == 'json_import'
            ).delete(synchronize_session=False)
            deleted_topic_ids.add(topic.id)
            deleted_in_this_file = True

        from app.grammar_lab.content_validator import validate_exercise_content
        for session in sessions:
            for ex in session.get('exercises', []):
                ex_type = ex.get('exercise_type', 'fill_blank')
                content = ex.get('content', {})
                content['source'] = 'json_import'

                try:
                    validate_exercise_content(ex_type, content)
                except ValueError as ve:
                    logger.warning(
                        'Skipping exercise in %s: invalid content (%s): %s',
                        filename, ex_type, ve,
                    )
                    continue

                raw_diff = ex.get('difficulty', 1)
                try:
                    diff_int = int(float(raw_diff))
                except (TypeError, ValueError):
                    diff_int = 1
                difficulty = max(1, min(3, diff_int))

                exercise = GrammarExercise(
                    topic_id=topic.id,
                    exercise_type=ex_type,
                    content=content,
                    difficulty=difficulty,
                    order=ex.get('order', 0)
                )
                db.session.add(exercise)
                exercises_imported += 1

        if exercises_imported or deleted:
            log_admin_action(
                current_user.id,
                'grammar_exercise.import_json',
                target_type='grammar_topic',
                target_id=topic.id,
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if deleted_in_this_file:
            deleted_topic_ids.discard(topic.id)
        logger.error("Error importing exercises from JSON file %s: %s", filename, e)
        return False, f'{filename}: ошибка импорта: {e}'

    return (
        True,
        f'{filename}: импортировано {exercises_imported} упражнений '
        f'для темы "{topic.title}" (slug {matched_slug}). '
        f'Удалено {deleted} старых.',
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

        deleted_topic_ids: set[int] = set()
        successes = 0
        for file in files:
            ok, message = _import_exercises_json_file(file, deleted_topic_ids)
            if ok:
                successes += 1
                flash(message, 'success')
            else:
                flash(message, 'danger')

        if successes:
            return redirect(url_for('grammar_lab_admin.grammar_lab_index'))
        return redirect(request.url)

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
