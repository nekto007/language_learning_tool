import random
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import func

from app.study.forms import StudySessionForm, StudySettingsForm
from app.study.models import GameScore, StudyItem, StudySession, StudySettings
from app.utils.db import db
from app.words.models import CollectionWords

study = Blueprint('study', __name__, template_folder='templates')


@study.route('/')
@login_required
def index():
    """Main study dashboard"""
    # Get study statistics
    due_items_count = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.next_review <= datetime.utcnow()).count()

    total_items = StudyItem.query.filter_by(user_id=current_user.id).count()

    # Get user's recent sessions
    recent_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .order_by(StudySession.start_time.desc()).limit(5).all()

    # Get learned words percentage
    total_words = CollectionWords.query.count()
    learned_words = StudyItem.query.filter_by(user_id=current_user.id).count()

    if total_words > 0:
        learned_percentage = int((learned_words / total_words) * 100)
    else:
        learned_percentage = 0

    # Get study session form
    form = StudySessionForm()

    return render_template(
        'study/index.html',
        due_items_count=due_items_count,
        total_items=total_items,
        learned_percentage=learned_percentage,
        recent_sessions=recent_sessions,
        form=form
    )


@study.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Study settings page"""
    # Get or create user settings
    user_settings = StudySettings.get_settings(current_user.id)

    form = StudySettingsForm(obj=user_settings)

    if form.validate_on_submit():
        form.populate_obj(user_settings)
        db.session.commit()
        flash(_('Your study settings have been updated!'), 'success')
        return redirect(url_for('study.index'))

    return render_template('study/settings.html', form=form)


@study.route('/cards')
@login_required
def cards():
    """Anki-style flashcard study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Create new study session
    session = StudySession(
        user_id=current_user.id,
        session_type='cards'
    )
    db.session.add(session)
    db.session.commit()

    return render_template(
        'study/cards.html',
        session_id=session.id,
        settings=settings,
        word_source=word_source
    )


@study.route('/quiz')
@login_required
def quiz():
    """Quiz study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Create new study session
    session = StudySession(
        user_id=current_user.id,
        session_type='quiz'
    )
    db.session.add(session)
    db.session.commit()

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source=word_source
    )


@study.route('/start-session', methods=['POST'])
@login_required
def start_session():
    """Start a new study session"""
    form = StudySessionForm()

    if form.validate_on_submit():
        session_type = form.session_type.data
        word_source = form.word_source.data

        if session_type == 'cards':
            return redirect(url_for('study.cards', word_source=word_source))
        elif session_type == 'quiz':
            return redirect(url_for('study.quiz', word_source=word_source))
        else:
            return redirect(url_for('study.matching', word_source=word_source))
            # return redirect(url_for('study.index'))

    flash(_('Invalid form data.'), 'danger')
    return redirect(url_for('study.index'))


# API routes for AJAX calls from study interfaces

@study.route('/api/get-study-items', methods=['GET'])
@login_required
def get_study_items():
    """Get words for study based on source and limits"""
    word_source = request.args.get('source', 'all')
    extra_study = request.args.get('extra_study', 'false').lower() == 'true'

    # Получаем настройки пользователя
    settings = StudySettings.get_settings(current_user.id)

    # Проверяем, были ли достигнуты дневные лимиты
    # Для этого нам нужно подсчитать, сколько новых карточек и повторений было сделано сегодня
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Получаем количество новых карточек, изученных сегодня
    new_cards_today = db.session.query(func.count(StudyItem.id)).filter(
        StudyItem.user_id == current_user.id,
        StudyItem.last_reviewed >= today_start,
        StudyItem.repetitions == 1  # Это новая карточка (первое изучение)
    ).scalar()

    # Получаем количество повторений, сделанных сегодня
    reviews_today = db.session.query(func.count(StudyItem.id)).filter(
        StudyItem.user_id == current_user.id,
        StudyItem.last_reviewed >= today_start,
        StudyItem.repetitions > 1  # Это повторение (не первое изучение)
    ).scalar()

    # Проверяем, достигнуты ли лимиты
    new_cards_limit_reached = new_cards_today >= settings.new_words_per_day
    reviews_limit_reached = reviews_today >= settings.reviews_per_day

    # Если оба лимита достигнуты и не запрошено дополнительное занятие, возвращаем пустой список
    # с особым статусом, чтобы фронтенд мог показать сообщение о завершении дневной нормы
    if not extra_study and new_cards_limit_reached and reviews_limit_reached:
        return jsonify({
            'status': 'daily_limit_reached',
            'message': 'Дневные лимиты достигнуты',
            'stats': {
                'new_cards_today': new_cards_today,
                'reviews_today': reviews_today,
                'new_cards_limit': settings.new_words_per_day,
                'reviews_limit': settings.reviews_per_day
            },
            'items': []
        })

    result_items = []

    # Определяем лимиты в зависимости от того, что уже изучено сегодня
    # Для обычного занятия - оставшиеся лимиты, для дополнительного - можно установить фиксированное число
    if extra_study:
        new_limit = 5  # Фиксированное количество для дополнительного занятия
        review_limit = 10
    else:
        new_limit = max(0, settings.new_words_per_day - new_cards_today)
        review_limit = max(0, settings.reviews_per_day - reviews_today)

    # Делим лимиты пополам, так как каждое слово создает 2 карточки (eng-rus и rus-eng)
    new_limit = max(1, new_limit // 2)
    review_limit = max(1, review_limit // 2)

    # Зависит от запрошенного источника - новые, изучаемые или все
    if word_source in ['new', 'all'] and new_limit > 0:
        # Получаем слова, которые пользователь еще не изучал
        existing_word_ids = db.session.query(StudyItem.word_id) \
            .filter_by(user_id=current_user.id).subquery()

        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(existing_word_ids),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(CollectionWords.id).limit(new_limit).all()

        # Добавляем новые слова в результат
        for word in new_words:
            audio_url = None
            if word.get_download == 1:
                audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

            result_items.append({
                'id': None,
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'definition': '',
                'examples': word.sentences,
                'audio_url': audio_url,
                'is_new': True
            })

    # Получаем слова в зависимости от источника
    if word_source == 'learning' and review_limit > 0:
        # Import user_word_status table
        from app.utils.db import user_word_status

        # Получаем слова со статусом 1 (learning) - по аналогии с другими режимами
        learning_words_query = db.session.query(CollectionWords) \
            .join(
            user_word_status,
            (CollectionWords.id == user_word_status.c.word_id) &
            (user_word_status.c.user_id == current_user.id)
        ) \
            .filter(
            user_word_status.c.status == 1,  # Status 1 = learning
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ) \
            .order_by(CollectionWords.id).limit(review_limit)

        learning_words = learning_words_query.all()

        # Добавляем слова в результат
        for word in learning_words:
            result_items.append({
                'id': None,  # Здесь могла бы быть привязка к StudyItem, но используем None
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'definition': '',
                'examples': word.sentences,
                'audio_url': url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')
                if hasattr(word, 'get_download') and word.get_download == 1 else None,
                'is_new': False
            })
    elif word_source == 'all' and review_limit > 0:
        # Для режима "all" продолжаем использовать существующую логику с просроченными карточками
        due_items = StudyItem.query.filter_by(user_id=current_user.id) \
            .filter(StudyItem.next_review <= datetime.utcnow().date() + timedelta(days=1)) \
            .order_by(StudyItem.next_review).limit(review_limit).all()

        # Добавляем карточки для повторения
        for item in due_items:
            word = item.word
            if not word or not word.russian_word:
                continue

            result_items.append({
                'id': item.id,
                'word_id': word.id,
                'word': word.english_word,
                'translation': word.russian_word,
                'examples': word.sentences,
                'audio_url': url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')
                if word.get_download else None,
                'is_new': False
            })

    # Возвращаем результаты с информацией о статусе
    return jsonify({
        'status': 'success',
        'stats': {
            'new_cards_today': new_cards_today,
            'reviews_today': reviews_today,
            'new_cards_limit': settings.new_words_per_day,
            'reviews_limit': settings.reviews_per_day
        },
        'items': result_items
    })


@study.route('/api/update-study-item', methods=['POST'])
@login_required
def update_study_item():
    """Update study item after review"""
    data = request.json
    word_id = data.get('word_id')
    quality = int(data.get('quality', 0))  # 0-5 rating
    session_id = data.get('session_id')

    # Get or create study item
    study_item = StudyItem.query.filter_by(user_id=current_user.id, word_id=word_id).first()

    if not study_item:
        # Create new study item if it doesn't exist
        study_item = StudyItem(user_id=current_user.id, word_id=word_id)
        db.session.add(study_item)

    # Update study item
    interval = study_item.update_after_review(quality)

    # Update session statistics if provided
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied += 1
            if quality >= 3:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'interval': interval,
        'next_review': study_item.next_review.strftime('%Y-%m-%d')
    })


@study.route('/api/complete-session', methods=['POST'])
@login_required
def complete_session():
    """Mark a study session as complete"""
    data = request.json
    session_id = data.get('session_id')

    session = StudySession.query.get(session_id)
    if session and session.user_id == current_user.id:
        session.complete_session()
        db.session.commit()

        return jsonify({
            'success': True,
            'stats': {
                'duration': session.duration,
                'words_studied': session.words_studied,
                'correct': session.correct_answers,
                'incorrect': session.incorrect_answers,
                'percentage': session.performance_percentage
            }
        })

    return jsonify({'success': False, 'message': 'Invalid session'})


@study.route('/stats')
@login_required
def stats():
    """Study statistics page"""
    # Get overall statistics
    total_items = StudyItem.query.filter_by(user_id=current_user.id).count()
    mastered_items = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.interval >= 30).count()

    # Calculate mastery percentage
    if total_items > 0:
        mastery_percentage = int((mastered_items / total_items) * 100)
    else:
        mastery_percentage = 0

    # Get recent sessions
    recent_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .order_by(StudySession.start_time.desc()).limit(10).all()

    # Get daily study statistics
    today = datetime.now().date()
    today_sessions = StudySession.query.filter_by(user_id=current_user.id) \
        .filter(func.date(StudySession.start_time) == today).all()

    # Calculate today's statistics
    today_words_studied = sum(session.words_studied for session in today_sessions)
    today_time_spent = sum(session.duration for session in today_sessions)

    # Get daily study streak
    # This would require more complex logic to track consecutive days
    study_streak = 0

    # Get words by stage (learning vs mastered)
    new_words = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.repetitions == 0).count()
    learning_words = StudyItem.query.filter_by(user_id=current_user.id) \
        .filter(StudyItem.repetitions > 0, StudyItem.interval < 30).count()
    mastered_words = mastered_items  # We already calculated this

    return render_template(
        'study/stats.html',
        total_items=total_items,
        mastered_items=mastered_items,
        mastery_percentage=mastery_percentage,
        recent_sessions=recent_sessions,
        study_streak=study_streak,
        today_words_studied=today_words_studied,
        today_time_spent=today_time_spent,
        new_words=new_words,
        learning_words=learning_words,
        mastered_words=mastered_words
    )


@study.route('/matching')
@login_required
def matching():
    """Matching game study interface"""
    # Get query parameters
    word_source = request.args.get('word_source', 'all')

    # Get user settings
    settings = StudySettings.get_settings(current_user.id)

    # Create new study session
    session = StudySession(
        user_id=current_user.id,
        session_type='matching'
    )
    db.session.add(session)
    db.session.commit()

    return render_template(
        'study/matching.html',
        session_id=session.id,
        settings=settings,
        word_source=word_source
    )


@study.route('/api/get-quiz-questions', methods=['GET'])
@login_required
def get_quiz_questions():
    """Get questions for quiz mode"""
    word_source = request.args.get('source', 'all')
    question_count = min(int(request.args.get('count', 20)), 50)  # Limit max questions

    # Get words based on source
    words = []

    # Import user_word_status table
    from app.utils.db import user_word_status

    if word_source in ['new', 'all']:
        # Get new words (not in study items)
        existing_word_ids = db.session.query(StudyItem.word_id) \
            .filter_by(user_id=current_user.id).subquery()

        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(existing_word_ids),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(question_count // 2).all()

        words.extend(new_words)

    if word_source in ['learning', 'all']:
        # Modified: Get words with status 1 (learning) if word_source is 'learning'
        if word_source == 'learning':
            # Get words being learned (status = 1)
            learning_words_query = db.session.query(CollectionWords) \
                .join(
                user_word_status,
                (CollectionWords.id == user_word_status.c.word_id) &
                (user_word_status.c.user_id == current_user.id)
            ) \
                .filter(
                user_word_status.c.status == 1,  # Status 1 = learning
                CollectionWords.russian_word != None,
                CollectionWords.russian_word != ''
            ) \
                .order_by(func.random()) \
                .limit(question_count - len(words))

            learning_words = learning_words_query.all()
            words.extend(learning_words)
        else:
            # Get words being learned (in study items)
            study_items = StudyItem.query.filter_by(user_id=current_user.id) \
                .order_by(func.random()).limit(question_count - len(words)).all()

            for item in study_items:
                if item.word and item.word.russian_word and item.word not in words:
                    words.append(item.word)

    # Ensure we have words to create questions
    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for quiz',
            'questions': []
        })

    # Generate questions from the words
    questions = generate_quiz_questions(words, question_count)

    return jsonify({
        'status': 'success',
        'questions': questions
    })


def generate_quiz_questions(words, count):
    """
    Generate quiz questions from words

    Question types:
    - multiple_choice: Multiple choice questions
    - true_false: True/False questions
    - fill_blank: Fill in the blank
    """
    questions = []

    # Ensure we don't try to create more questions than words
    count = min(count, len(words) * 2)

    # Create a list of all the words for creating distractors
    all_words = CollectionWords.query.filter(
        CollectionWords.russian_word != None,
        CollectionWords.russian_word != ''
    ).all()

    # Create two questions per word (eng->rus and rus->eng)
    for word in words:
        if len(questions) >= count:
            break

        # Skip words without translations
        if not word.russian_word or word.russian_word.strip() == '':
            continue

        # Generate English to Russian question
        if len(questions) < count:
            question_type = random.choice(['multiple_choice', 'true_false', 'fill_blank'])

            if question_type == 'multiple_choice':
                # Create multiple choice question (eng->rus)
                question = create_multiple_choice_question(word, all_words, 'eng_to_rus')
                questions.append(question)

            elif question_type == 'true_false':
                # Create true/false question (eng->rus)
                question = create_true_false_question(word, all_words, 'eng_to_rus')
                questions.append(question)

            elif question_type == 'fill_blank':
                # Create fill-in-the-blank question (eng->rus)
                question = create_fill_blank_question(word, 'eng_to_rus')
                questions.append(question)

        # Generate Russian to English question
        if len(questions) < count:
            question_type = random.choice(['multiple_choice', 'true_false', 'fill_blank'])

            if question_type == 'multiple_choice':
                # Create multiple choice question (rus->eng)
                question = create_multiple_choice_question(word, all_words, 'rus_to_eng')
                questions.append(question)

            elif question_type == 'true_false':
                # Create true/false question (rus->eng)
                question = create_true_false_question(word, all_words, 'rus_to_eng')
                questions.append(question)

            elif question_type == 'fill_blank':
                # Create fill-in-the-blank question (rus->eng)
                question = create_fill_blank_question(word, 'rus_to_eng')
                questions.append(question)

    # Shuffle the questions
    random.shuffle(questions)

    # Limit to requested count
    return questions[:count]


def create_multiple_choice_question(word, all_words, direction):
    """Create a multiple choice question"""
    if direction == 'eng_to_rus':
        question_text = f'What is the translation of "{word.english_word}"?'
        correct_answer = word.russian_word

        # Find distractors (other Russian words)
        distractors = []
        for distractor_word in random.sample(all_words, min(10, len(all_words))):
            if (distractor_word.id != word.id and
                    distractor_word.russian_word and
                    distractor_word.russian_word != correct_answer):
                distractors.append(distractor_word.russian_word)
                if len(distractors) >= 3:
                    break
    else:
        question_text = f'What is the English word for "{word.russian_word}"?'
        correct_answer = word.english_word

        # Find distractors (other English words)
        distractors = []
        for distractor_word in random.sample(all_words, min(10, len(all_words))):
            if (distractor_word.id != word.id and
                    distractor_word.english_word and
                    distractor_word.english_word != correct_answer):
                distractors.append(distractor_word.english_word)
                if len(distractors) >= 3:
                    break

    # Create options and shuffle
    options = [correct_answer] + distractors
    random.shuffle(options)

    # Audio for English word
    audio_url = None
    if direction == 'eng_to_rus' and word.get_download == 1:
        audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

    return {
        'id': f'mc_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'multiple_choice',
        'text': question_text,
        'options': options,
        'answer': correct_answer,
        'hint': f'Choose the correct translation',
        'audio_url': audio_url
    }


def create_true_false_question(word, all_words, direction):
    """Create a true/false question"""
    # Decide if question will be true or false
    is_true = random.choice([True, False])

    if direction == 'eng_to_rus':
        english_word = word.english_word

        if is_true:
            russian_word = word.russian_word
            answer = 'true'
        else:
            # Find a different Russian word
            other_words = [w for w in all_words if w.id != word.id and w.russian_word]
            if other_words:
                other_word = random.choice(other_words)
                russian_word = other_word.russian_word
            else:
                # If no other words available, make up a fake translation
                russian_word = word.russian_word + 'ский'
            answer = 'false'

        question_text = f'Does "{english_word}" translate to "{russian_word}"?'

    else:
        russian_word = word.russian_word

        if is_true:
            english_word = word.english_word
            answer = 'true'
        else:
            # Find a different English word
            other_words = [w for w in all_words if w.id != word.id and w.english_word]
            if other_words:
                other_word = random.choice(other_words)
                english_word = other_word.english_word
            else:
                # If no other words available, make up a fake translation
                english_word = 'un' + word.english_word
            answer = 'false'

        question_text = f'Does "{russian_word}" translate to "{english_word}"?'

    # Audio for English word
    audio_url = None
    # if word.get_download == 1:
    #     audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

    return {
        'id': f'tf_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'true_false',
        'text': question_text,
        'answer': answer,
        'hint': f'Think about the correct translation',
        'audio_url': audio_url
    }


def create_fill_blank_question(word, direction):
    """Create a fill-in-the-blank question"""
    if direction == 'eng_to_rus':
        question_text = f'Translate "{word.english_word}" to Russian:'
        answer = word.russian_word
    else:
        question_text = f'Translate "{word.russian_word}" to English:'
        answer = word.english_word

    # Get acceptable alternative answers
    acceptable_answers = [answer]

    # If the answer contains commas, each part is an acceptable answer
    if ',' in answer:
        alternative_answers = [a.strip() for a in answer.split(',')]
        acceptable_answers.extend(alternative_answers)

    # Audio for English word
    audio_url = None
    if direction == 'eng_to_rus' and word.get_download == 1:
        audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

    return {
        'id': f'fb_{word.id}_{direction}',
        'word_id': word.id,
        'type': 'fill_blank',
        'text': question_text,
        'answer': answer,
        'acceptable_answers': acceptable_answers,
        'hint': f'Type the translation',
        'audio_url': audio_url
    }


@study.route('/api/submit-quiz-answer', methods=['POST'])
@login_required
def submit_quiz_answer():
    """Process a submitted quiz answer"""
    data = request.json
    session_id = data.get('session_id')
    word_id = data.get('word_id')
    is_correct = data.get('is_correct', False)

    # Get or create study item
    study_item = StudyItem.query.filter_by(user_id=current_user.id, word_id=word_id).first()

    if not study_item:
        # Create new study item if it doesn't exist
        study_item = StudyItem(user_id=current_user.id, word_id=word_id)
        db.session.add(study_item)

    # Convert boolean correct to quality score (0-5)
    quality = 4 if is_correct else 1

    # Update study item
    interval = study_item.update_after_review(quality)

    # Update session statistics if provided
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied += 1
            if is_correct:
                session.correct_answers += 1
            else:
                session.incorrect_answers += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'interval': interval,
        'next_review': study_item.next_review.strftime('%Y-%m-%d')
    })


@study.route('/api/get-matching-words', methods=['GET'])
@login_required
def get_matching_words():
    """Get words for matching game"""
    word_source = request.args.get('source', 'all')
    word_count = min(int(request.args.get('count', 10)), 20)  # Limit max pairs

    # Добавляем отладочную информацию
    print(f"Запрос слов для matching game, source={word_source}, count={word_count}")

    # Get words based on source
    words = []

    # Import user_word_status table
    from app.utils.db import user_word_status

    if word_source == 'learning':
        # Используем только слова со статусом 1 (learning)
        print("Выбираем слова со статусом 'learning'")

        # Делаем запрос явно через join и фильтр по статусу
        learning_words_query = db.session.query(CollectionWords) \
            .join(
            user_word_status,
            (CollectionWords.id == user_word_status.c.word_id) &
            (user_word_status.c.user_id == current_user.id)
        ) \
            .filter(
            user_word_status.c.status == 1,  # Status 1 = learning
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ) \
            .order_by(func.random()) \
            .limit(word_count)

        learning_words = learning_words_query.all()
        print(f"Найдено {len(learning_words)} слов со статусом 'learning'")

        # Список ID слов для отладки
        word_ids = [word.id for word in learning_words]
        print(f"ID слов: {word_ids}")

        words.extend(learning_words)

    elif word_source == 'new':
        # Get new words (not in study items)
        print("Выбираем новые слова")
        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(
                db.session.query(user_word_status.c.word_id)
                .filter(user_word_status.c.user_id == current_user.id)
            ),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(word_count).all()

        print(f"Найдено {len(new_words)} новых слов")
        words.extend(new_words)

    elif word_source == 'all':
        print("Выбираем смешанные слова (new + learning)")
        # Сначала добавим слова со статусом learning (примерно половину)
        learning_words_query = db.session.query(CollectionWords) \
            .join(
            user_word_status,
            (CollectionWords.id == user_word_status.c.word_id) &
            (user_word_status.c.user_id == current_user.id)
        ) \
            .filter(
            user_word_status.c.status == 1,  # Status 1 = learning
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ) \
            .order_by(func.random()) \
            .limit(word_count // 2)

        learning_words = learning_words_query.all()
        print(f"Найдено {len(learning_words)} слов со статусом 'learning'")
        words.extend(learning_words)

        # Затем добавим новые слова до нужного количества
        if len(words) < word_count:
            new_words = CollectionWords.query.filter(
                ~CollectionWords.id.in_(
                    db.session.query(user_word_status.c.word_id)
                    .filter(user_word_status.c.user_id == current_user.id)
                ),
                CollectionWords.russian_word != None,
                CollectionWords.russian_word != ''
            ).order_by(func.random()).limit(word_count - len(words)).all()

            print(f"Найдено {len(new_words)} новых слов")
            words.extend(new_words)

    # Ensure we have words
    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for matching game',
            'words': []
        })

    # Format the words for the game
    game_words = []
    for word in words:
        # Skip words without translations
        if not word.russian_word or word.russian_word.strip() == '':
            continue

        # Format example if available
        example = None
        if word.sentences:
            example = word.sentences

        # Get audio URL if available
        audio_url = None
        if hasattr(word, 'get_download') and word.get_download == 1:
            audio_url = url_for('static', filename=f'audio/pronunciation_en_{word.english_word}.mp3')

        game_words.append({
            'id': word.id,
            'word': word.english_word,
            'translation': word.russian_word,
            'example': example,
            'audio_url': audio_url
        })

    print(f"Отправляем {len(game_words)} слов для игры")

    return jsonify({
        'status': 'success',
        'words': game_words
    })


@study.route('/api/complete-matching-game', methods=['POST'])
@login_required
def complete_matching_game():
    """Process a completed matching game"""
    data = request.json
    session_id = data.get('session_id')
    difficulty = data.get('difficulty', 'easy')
    pairs_matched = data.get('pairs_matched', 0)
    total_pairs = data.get('total_pairs', 0)
    moves = data.get('moves', 0)
    time_taken = data.get('time_taken', 0)
    score = data.get('score', 0)

    # Добавим отладочную информацию
    print(f"Получены данные игры: {data}")

    # Update session
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied = total_pairs
            session.correct_answers = pairs_matched
            session.complete_session()
            db.session.commit()
            print(f"Обновлена сессия: {session_id}")

    try:
        # Save score to leaderboard
        game_score = GameScore(
            user_id=current_user.id,
            game_type='matching',
            difficulty=difficulty,
            score=score,
            time_taken=time_taken,
            pairs_matched=pairs_matched,
            total_pairs=total_pairs,
            moves=moves,
            date_achieved=datetime.utcnow()
        )

        # Явно добавляем объект в сессию и коммитим изменения
        db.session.add(game_score)
        db.session.commit()

        print(f"Сохранен результат игры: {game_score.id}")

        # Get user's rank
        rank = game_score.get_rank()

        # Get personal best
        personal_best = db.session.query(func.max(GameScore.score)).filter(
            GameScore.user_id == current_user.id,
            GameScore.game_type == 'matching',
            GameScore.difficulty == difficulty
        ).scalar() or 0

        is_personal_best = score >= personal_best

        return jsonify({
            'success': True,
            'score': score,
            'rank': rank,
            'is_personal_best': is_personal_best,
            'game_score_id': game_score.id  # Возвращаем ID созданной записи для проверки
        })
    except Exception as e:
        # В случае ошибки откатываем транзакцию и логируем ошибку
        db.session.rollback()
        print(f"Ошибка при сохранении результата: {str(e)}")
        import traceback
        traceback.print_exc()

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@study.route('/api/complete-quiz', methods=['POST'])
@login_required
def complete_quiz():
    """Process a completed quiz"""
    data = request.json
    session_id = data.get('session_id')
    score = data.get('score', 0)
    total_questions = data.get('total_questions', 0)
    correct_answers = data.get('correct_answers', 0)
    time_taken = data.get('time_taken', 0)

    # Update session
    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.complete_session()

    # Save score to leaderboard
    game_score = GameScore(
        user_id=current_user.id,
        game_type='quiz',
        score=score,
        time_taken=time_taken,
        correct_answers=correct_answers,
        total_questions=total_questions,
        date_achieved=datetime.utcnow()
    )
    db.session.add(game_score)
    db.session.commit()

    # Get user's rank
    rank = game_score.get_rank()

    # Get personal best
    personal_best = db.session.query(func.max(GameScore.score)).filter(
        GameScore.user_id == current_user.id,
        GameScore.game_type == 'quiz'
    ).scalar() or 0

    is_personal_best = score >= personal_best

    return jsonify({
        'success': True,
        'score': score,
        'rank': rank,
        'is_personal_best': is_personal_best
    })

@study.route('/leaderboard')
@login_required
def leaderboard():
    """Show leaderboard for games"""
    return render_template('study/leaderboard.html')

@study.route('/api/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    """Get leaderboard for a game"""
    difficulty = request.args.get('difficulty')
    limit = min(int(request.args.get('limit', 10)), 50)  # Limit max entries

    leaderboard = GameScore.get_leaderboard(game_type, difficulty, limit)

    # Format leaderboard data
    leaderboard_data = []
    for i, entry in enumerate(leaderboard):
        user_data = {
            'rank': i + 1,
            'username': entry.user.username,
            'score': entry.score,
            'time_taken': entry.time_taken,
            'date': entry.date_achieved.strftime('%Y-%m-%d %H:%M')
        }

        if game_type == 'matching':
            user_data.update({
                'pairs_matched': entry.pairs_matched,
                'total_pairs': entry.total_pairs,
                'moves': entry.moves
            })
        elif game_type == 'quiz':
            user_data.update({
                'correct_answers': entry.correct_answers,
                'total_questions': entry.total_questions
            })

        leaderboard_data.append(user_data)

    # Get user's best score
    user_best = db.session.query(GameScore).filter(
        GameScore.user_id == current_user.id,
        GameScore.game_type == game_type
    )

    if difficulty:
        user_best = user_best.filter_by(difficulty=difficulty)

    user_best = user_best.order_by(GameScore.score.desc()).first()

    user_best_data = None
    if user_best:
        user_rank = user_best.get_rank()
        user_best_data = {
            'rank': user_rank,
            'score': user_best.score,
            'time_taken': user_best.time_taken,
            'date': user_best.date_achieved.strftime('%Y-%m-%d %H:%M')
        }

        if game_type == 'matching':
            user_best_data.update({
                'pairs_matched': user_best.pairs_matched,
                'total_pairs': user_best.total_pairs,
                'moves': user_best.moves
            })
        elif game_type == 'quiz':
            user_best_data.update({
                'correct_answers': user_best.correct_answers,
                'total_questions': user_best.total_questions
            })

    return jsonify({
        'status': 'success',
        'leaderboard': leaderboard_data,
        'user_best': user_best_data
    })
