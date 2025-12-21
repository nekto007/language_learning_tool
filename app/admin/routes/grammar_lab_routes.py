# app/admin/routes/grammar_lab_routes.py

"""
Grammar Lab Admin Routes
CRUD операции для управления грамматическими темами и упражнениями
"""
import json
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from app.admin.utils.decorators import admin_required
from app.utils.db import db
from app.grammar_lab.models import GrammarTopic, GrammarExercise

grammar_lab_bp = Blueprint('grammar_lab_admin', __name__)
logger = logging.getLogger(__name__)


@grammar_lab_bp.route('/grammar-lab')
@login_required
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

    for level in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']:
        count = sum(1 for t in topics if t.level == level)
        stats['by_level'][level] = count

    return render_template(
        'admin/grammar_lab/index.html',
        topics=topics,
        stats=stats
    )


@grammar_lab_bp.route('/grammar-lab/topics')
@login_required
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
@login_required
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
            db.session.commit()

            flash(f'Topic "{title}" created successfully!', 'success')
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic.id))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating topic: {e}")
            flash(f'Error creating topic: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/topic_form.html', topic=None)


@grammar_lab_bp.route('/grammar-lab/topics/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_topic(topic_id):
    """Edit a grammar topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)

    if request.method == 'POST':
        try:
            topic.slug = request.form.get('slug', topic.slug).strip()
            topic.title = request.form.get('title', topic.title).strip()
            topic.title_ru = request.form.get('title_ru', topic.title_ru).strip()
            topic.level = request.form.get('level', topic.level)
            topic.order = int(request.form.get('order', topic.order))
            topic.estimated_time = int(request.form.get('estimated_time', topic.estimated_time))
            topic.difficulty = int(request.form.get('difficulty', topic.difficulty))

            # Parse content JSON
            content_json = request.form.get('content', '{}')
            try:
                topic.content = json.loads(content_json) if content_json else {}
            except json.JSONDecodeError:
                pass  # Keep existing content

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
@login_required
@admin_required
def delete_topic(topic_id):
    """Delete a grammar topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)
    title = topic.title

    try:
        db.session.delete(topic)
        db.session.commit()
        flash(f'Topic "{title}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting topic: {str(e)}', 'danger')

    return redirect(url_for('grammar_lab_admin.topic_list'))


# ============ Exercise Routes ============

@grammar_lab_bp.route('/grammar-lab/topics/<int:topic_id>/exercises/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_exercise(topic_id):
    """Create a new exercise for a topic"""
    topic = GrammarTopic.query.get_or_404(topic_id)

    if request.method == 'POST':
        try:
            exercise_type = request.form.get('exercise_type', 'fill_blank')
            order = int(request.form.get('order', 0))
            difficulty = int(request.form.get('difficulty', 1))

            # Parse content JSON
            content_json = request.form.get('content', '{}')
            try:
                content = json.loads(content_json)
            except json.JSONDecodeError:
                flash('Invalid JSON in content field', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None)

            exercise = GrammarExercise(
                topic_id=topic_id,
                exercise_type=exercise_type,
                content=content,
                difficulty=difficulty,
                order=order
            )
            db.session.add(exercise)
            db.session.commit()

            flash('Exercise created successfully!', 'success')
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic_id))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating exercise: {e}")
            flash(f'Error creating exercise: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=None)


@grammar_lab_bp.route('/grammar-lab/exercises/<int:exercise_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_exercise(exercise_id):
    """Edit an exercise"""
    exercise = GrammarExercise.query.get_or_404(exercise_id)
    topic = exercise.topic

    if request.method == 'POST':
        try:
            exercise.exercise_type = request.form.get('exercise_type', exercise.exercise_type)
            exercise.order = int(request.form.get('order', exercise.order))
            exercise.difficulty = int(request.form.get('difficulty', exercise.difficulty))

            content_json = request.form.get('content', '{}')
            try:
                exercise.content = json.loads(content_json)
            except json.JSONDecodeError:
                flash('Invalid JSON in content field', 'danger')
                return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise)

            db.session.commit()
            flash('Exercise updated successfully!', 'success')
            return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating exercise: {str(e)}', 'danger')

    return render_template('admin/grammar_lab/exercise_form.html', topic=topic, exercise=exercise)


@grammar_lab_bp.route('/grammar-lab/exercises/<int:exercise_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_exercise(exercise_id):
    """Delete an exercise"""
    exercise = GrammarExercise.query.get_or_404(exercise_id)
    topic_id = exercise.topic_id

    try:
        db.session.delete(exercise)
        db.session.commit()
        flash('Exercise deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting exercise: {str(e)}', 'danger')

    return redirect(url_for('grammar_lab_admin.edit_topic', topic_id=topic_id))


# ============ API Endpoints ============

@grammar_lab_bp.route('/grammar-lab/api/topics', methods=['GET'])
@login_required
@admin_required
def api_topics():
    """Get all topics as JSON"""
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()
    return jsonify([t.to_dict() for t in topics])


@grammar_lab_bp.route('/grammar-lab/api/topic/<int:topic_id>/exercises', methods=['GET'])
@login_required
@admin_required
def api_topic_exercises(topic_id):
    """Get exercises for a topic"""
    exercises = GrammarExercise.query.filter_by(topic_id=topic_id).order_by(
        GrammarExercise.order
    ).all()
    return jsonify([e.to_dict() for e in exercises])
