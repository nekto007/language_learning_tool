import logging
import random
from datetime import datetime, timezone

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError, OperationalError

from app.study.blueprint import study, get_audio_url_for_word
from app.study.models import GameScore, StudySession, StudySettings, UserCardDirection, UserWord
from app.utils.db import db
from app.words.models import CollectionWords
from app.modules.decorators import module_required
from app.study.services import (
    DeckService, SessionService, QuizService, StatsService
)

logger = logging.getLogger(__name__)

LINEAR_PLAN_DECK_QUIZ_SOURCE = 'linear_plan_deck_quiz'
LINEAR_PLAN_DECK_QUIZ_DEFAULT_LIMIT = 30
LINEAR_PLAN_DECK_QUIZ_MAX_LIMIT = 30


@study.route('/quiz')
@login_required
@module_required('study')
def quiz():
    my_decks = DeckService.get_user_decks(current_user.id, include_public=False)

    from app.study.models import QuizDeck
    public_decks = QuizDeck.query.filter(
        QuizDeck.is_public == True,
        QuizDeck.user_id != current_user.id
    ).order_by(QuizDeck.times_played.desc()).limit(10).all()

    return render_template(
        'study/quiz_deck_select.html',
        my_decks=my_decks,
        public_decks=public_decks
    )


@study.route('/quiz/auto')
@login_required
@module_required('study')
def quiz_auto():
    settings = StudySettings.get_settings(current_user.id)
    word_limit = request.args.get('limit', type=int)
    session = SessionService.start_session(current_user.id, 'quiz')

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source='auto',
        deck_id=None,
        word_limit=word_limit
    )


@study.route('/quiz/linear-plan')
@login_required
@module_required('study')
def quiz_linear_plan():
    settings = StudySettings.get_settings(current_user.id)
    word_limit = request.args.get(
        'limit',
        default=LINEAR_PLAN_DECK_QUIZ_DEFAULT_LIMIT,
        type=int,
    )
    word_limit = min(
        max(word_limit or LINEAR_PLAN_DECK_QUIZ_DEFAULT_LIMIT, 1),
        LINEAR_PLAN_DECK_QUIZ_MAX_LIMIT,
    )
    session = SessionService.start_session(current_user.id, 'quiz')

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source=LINEAR_PLAN_DECK_QUIZ_SOURCE,
        deck_id=None,
        deck_title='Квиз по словам из колод',
        word_limit=word_limit,
    )


@study.route('/quiz/deck/<int:deck_id>')
@login_required
@module_required('study')
def quiz_deck(deck_id):
    from app.study.models import QuizDeck

    deck = QuizDeck.query.get_or_404(deck_id)

    if not deck.is_public and deck.user_id != current_user.id:
        flash('У вас нет доступа к этой колоде', 'danger')
        return redirect(url_for('study.quiz'))

    if deck.word_count == 0:
        flash('В колоде нет слов', 'warning')
        return redirect(url_for('study.quiz'))

    settings = StudySettings.get_settings(current_user.id)
    word_limit = request.args.get('limit', type=int)

    session = SessionService.start_session(current_user.id, 'quiz')

    deck.times_played += 1
    db.session.commit()

    return render_template(
        'study/quiz.html',
        session_id=session.id,
        settings=settings,
        word_source='deck',
        deck_id=deck_id,
        deck_title=deck.title,
        word_limit=word_limit
    )


@study.route('/quiz/shared/<code>')
def quiz_deck_shared(code):
    from flask import abort
    from app.study.models import QuizDeck, QuizDeckWord
    from app.words.models import CollectionWords

    deck = QuizDeck.query.filter_by(share_code=code, is_public=True).first()
    if not deck:
        abort(404)

    if current_user.is_authenticated:
        return redirect(url_for('study.quiz_deck', deck_id=deck.id))

    word_count = deck.words.count()
    preview_words = (
        db.session.query(CollectionWords)
        .join(QuizDeckWord, QuizDeckWord.word_id == CollectionWords.id)
        .filter(QuizDeckWord.deck_id == deck.id)
        .limit(5)
        .all()
    )

    deck_level = None
    if preview_words:
        levels = [w.level for w in preview_words if w.level]
        if levels:
            deck_level = max(set(levels), key=levels.count)

    meta_description = f'Quiz: {deck.title} — {word_count} слов'
    if deck_level:
        meta_description += f', уровень {deck_level}'

    return render_template(
        'study/quiz_shared_public.html',
        deck=deck,
        word_count=word_count,
        preview_words=preview_words,
        deck_level=deck_level,
        meta_description=meta_description,
    )


@study.route('/matching')
@login_required
@module_required('study')
def matching():
    settings = StudySettings.get_settings(current_user.id)
    session = SessionService.start_session(current_user.id, 'matching')

    return render_template(
        'study/matching.html',
        session_id=session.id,
        settings=settings,
        word_source='auto'
    )


@study.route('/leaderboard')
@login_required
def leaderboard():
    from app.curriculum.cache import cache

    cache_key_xp = 'leaderboard_xp_top100'
    cache_key_ach = 'leaderboard_achievements_top100'

    top_xp_users = cache.get(cache_key_xp)
    if not top_xp_users:
        top_xp_users = StatsService.get_xp_leaderboard(limit=100)
        cache.set(cache_key_xp, top_xp_users, timeout=300)

    top_achievement_users = cache.get(cache_key_ach)
    if not top_achievement_users:
        top_achievement_users = StatsService.get_achievement_leaderboard(limit=100)
        cache.set(cache_key_ach, top_achievement_users, timeout=300)

    current_user_xp_rank = StatsService.get_user_xp_rank(current_user.id)
    current_user_achievement_rank = StatsService.get_user_achievement_rank(current_user.id)

    return render_template(
        'study/leaderboard.html',
        top_xp_users=top_xp_users,
        top_achievement_users=top_achievement_users,
        current_user_xp_rank=current_user_xp_rank,
        current_user_achievement_rank=current_user_achievement_rank
    )


@study.route('/achievements')
@login_required
def achievements():
    data = StatsService.get_achievements_by_category(current_user.id)

    from app.study.models import Achievement
    total_xp_available = sum(
        ach.xp_reward for ach in Achievement.query.all()
    )

    return render_template(
        'study/achievements.html',
        achievements_by_category=data['by_category'],
        total_achievements=data['total_achievements'],
        earned_count=data['earned_count'],
        total_xp_available=total_xp_available,
        earned_xp=data['total_xp_earned']
    )


# ============ Game API Endpoints ============


@study.route('/api/get-quiz-questions', methods=['GET'])
@login_required
def get_quiz_questions():
    from app.study.models import QuizDeck, QuizDeckWord

    source = request.args.get('source', 'auto')
    requested_count = request.args.get('count', type=int)
    if source == LINEAR_PLAN_DECK_QUIZ_SOURCE:
        question_count = min(
            max(requested_count or LINEAR_PLAN_DECK_QUIZ_DEFAULT_LIMIT, 1),
            LINEAR_PLAN_DECK_QUIZ_MAX_LIMIT,
        )
    else:
        question_count = min(max(requested_count or 20, 1), 200)
    deck_id = request.args.get('deck_id', type=int)

    words = []

    class DeckWordAdapter:
        def __init__(self, deck_word):
            self.id = deck_word.id
            self.english_word = deck_word.english_word
            self.russian_word = deck_word.russian_word
            self.get_download = 0
            self.listening = None
            if deck_word.word_id and deck_word.word:
                self.id = deck_word.word_id
                self.get_download = deck_word.word.get_download
                self.listening = deck_word.word.listening

    if deck_id:
        deck = QuizDeck.query.get_or_404(deck_id)

        if not deck.is_public and deck.user_id != current_user.id:
            return jsonify({
                'status': 'error',
                'message': 'Access denied',
                'questions': []
            }), 403

        deck_words = deck.words.order_by(QuizDeckWord.order_index).all()

        if not deck_words:
            return jsonify({
                'status': 'error',
                'message': 'No words in deck',
                'questions': []
            })

        words = [DeckWordAdapter(dw) for dw in deck_words]

        if len(words) > question_count:
            words = random.sample(words, question_count)

    elif source == LINEAR_PLAN_DECK_QUIZ_SOURCE:
        valid_collection_word = and_(
            QuizDeckWord.word_id.isnot(None),
            CollectionWords.english_word.isnot(None),
            CollectionWords.english_word != '',
            CollectionWords.russian_word.isnot(None),
            CollectionWords.russian_word != '',
        )
        valid_custom_word = and_(
            QuizDeckWord.custom_english.isnot(None),
            QuizDeckWord.custom_english != '',
            QuizDeckWord.custom_russian.isnot(None),
            QuizDeckWord.custom_russian != '',
        )
        deck_words = (
            db.session.query(QuizDeckWord)
            .join(QuizDeck, QuizDeckWord.deck_id == QuizDeck.id)
            .outerjoin(CollectionWords, QuizDeckWord.word_id == CollectionWords.id)
            .filter(
                QuizDeck.user_id == current_user.id,
                or_(valid_collection_word, valid_custom_word),
            )
            .order_by(func.random())
            .limit(max(question_count * 10, 100))
            .all()
        )

        seen: set[object] = set()
        for deck_word in deck_words:
            if not deck_word.english_word or not deck_word.russian_word:
                continue
            key = (
                deck_word.word_id
                if deck_word.word_id is not None
                else (
                    'custom',
                    deck_word.english_word.strip().lower(),
                    deck_word.russian_word.strip().lower(),
                )
            )
            if key in seen:
                continue
            seen.add(key)
            words.append(DeckWordAdapter(deck_word))
            if len(words) >= question_count:
                break

    else:
        learning_words = db.session.query(CollectionWords).join(
            UserWord,
            (CollectionWords.id == UserWord.word_id) &
            (UserWord.user_id == current_user.id)
        ).filter(
            UserWord.status.in_(['learning', 'review']),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(question_count // 2).all()

        words.extend(learning_words)

        if len(words) < question_count:
            new_words = CollectionWords.query.filter(
                ~CollectionWords.id.in_(
                    db.session.query(UserWord.word_id)
                    .filter(UserWord.user_id == current_user.id)
                ),
                CollectionWords.russian_word != None,
                CollectionWords.russian_word != ''
            ).order_by(func.random()).limit(question_count - len(words)).all()

            words.extend(new_words)

    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for quiz',
            'questions': []
        })

    questions = QuizService.generate_quiz_questions(words, question_count, get_audio_url_for_word)

    return jsonify({
        'status': 'success',
        'questions': questions
    })


@study.route('/api/submit-quiz-answer', methods=['POST'])
@login_required
def submit_quiz_answer():
    if not request.is_json:
        return jsonify({'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    session_id = data.get('session_id')
    is_correct = data.get('is_correct', False)

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
        'success': True
    })


@study.route('/api/get-matching-words', methods=['GET'])
@login_required
def get_matching_words():
    word_count = min(int(request.args.get('count', 10)), 20)

    words = []

    learning_words = db.session.query(CollectionWords).join(
        UserWord,
        (CollectionWords.id == UserWord.word_id) &
        (UserWord.user_id == current_user.id)
    ).filter(
        UserWord.status.in_(['learning', 'review']),
        CollectionWords.russian_word != None,
        CollectionWords.russian_word != ''
    ).order_by(func.random()).limit(word_count // 2).all()

    words.extend(learning_words)

    if len(words) < word_count:
        new_words = CollectionWords.query.filter(
            ~CollectionWords.id.in_(
                db.session.query(UserWord.word_id)
                .filter(UserWord.user_id == current_user.id)
            ),
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).order_by(func.random()).limit(word_count - len(words)).all()

        words.extend(new_words)

    if not words:
        return jsonify({
            'status': 'error',
            'message': 'No words available for matching game',
            'words': []
        })

    game_words = []
    for word in words:
        if not word.russian_word or word.russian_word.strip() == '':
            continue

        example = None
        if word.sentences:
            example = word.sentences

        audio_url = get_audio_url_for_word(word)

        game_words.append({
            'id': word.id,
            'word': word.english_word,
            'translation': word.russian_word,
            'example': example,
            'audio_url': audio_url
        })

    return jsonify({
        'status': 'success',
        'words': game_words
    })


def _calculate_matching_score(difficulty, pairs_matched, total_pairs, time_taken, moves):
    if difficulty not in ['easy', 'medium', 'hard']:
        return 0

    settings = {
        'easy': {'time_limit': 60, 'multiplier': 1},
        'medium': {'time_limit': 120, 'multiplier': 1.5},
        'hard': {'time_limit': 180, 'multiplier': 2}
    }

    config = settings[difficulty]
    time_limit = config['time_limit']
    multiplier = config['multiplier']

    if not (0 <= pairs_matched <= total_pairs):
        return 0
    if time_taken < 0 or moves < 0:
        return 0
    if total_pairs == 0:
        return 0
    if moves < pairs_matched * 2:
        return 0

    time_bonus = max(0, time_limit - time_taken)
    move_efficiency = min(1.0, (total_pairs * 2) / moves) if moves > 0 else 0

    base_score = (
        (pairs_matched * 10) +
        (time_bonus * 2) +
        (move_efficiency * 30)
    )

    score = int(base_score * multiplier)

    return max(0, min(score, 500))


@study.route('/api/complete-matching-game', methods=['POST'])
@login_required
def complete_matching_game():
    if not request.is_json:
        return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    session_id = data.get('session_id')
    difficulty = data.get('difficulty', 'easy')

    try:
        pairs_matched = int(data.get('pairs_matched', 0))
        total_pairs = int(data.get('total_pairs', 0))
        moves = int(data.get('moves', 0))
        time_taken = int(data.get('time_taken', 0))
        word_ids = data.get('word_ids', [])
    except (ValueError, TypeError):
        return jsonify({
            'success': False,
            'error': 'Invalid game data'
        }), 400

    score = _calculate_matching_score(difficulty, pairs_matched, total_pairs, time_taken, moves)

    if score == 0 and (pairs_matched > 0 or total_pairs > 0):
        if pairs_matched > total_pairs or moves < pairs_matched * 2:
            return jsonify({
                'success': False,
                'error': 'Invalid game data detected'
            }), 200

    from app.study.xp_service import XPService
    from app.achievements.xp_service import award_game_xp_idempotent, get_level_info
    from app.achievements.models import UserStatistics as _UserStats
    score_percentage = (pairs_matched / total_pairs * 100) if total_pairs > 0 else 0
    xp_breakdown = XPService.calculate_matching_xp(
        score=score_percentage,
        total_pairs=total_pairs
    )
    xp_award = None
    if xp_breakdown['total_xp'] > 0:
        xp_award = award_game_xp_idempotent(
            current_user.id,
            int(session_id) if session_id else None,
            'matching',
            xp_breakdown['total_xp'],
            datetime.now(timezone.utc).date(),
        )
        db.session.commit()
    _matching_stats = _UserStats.query.filter_by(user_id=current_user.id).first()
    _matching_total_xp = int(_matching_stats.total_xp or 0) if _matching_stats else 0
    _matching_level = get_level_info(_matching_total_xp).current_level

    if word_ids and pairs_matched > 0:
        performance = pairs_matched / total_pairs if total_pairs > 0 else 0
        efficiency = (total_pairs * 2) / moves if moves > 0 else 0

        if performance >= 1.0 and efficiency > 0.8:
            quality = 4
        elif performance >= 1.0:
            quality = 3
        elif performance >= 0.7:
            quality = 2
        else:
            quality = 0

        srs_errors = []
        for word_id in word_ids:
            try:
                with db.session.begin_nested():
                    user_word = UserWord.get_or_create(current_user.id, word_id)

                    for direction_str in ['eng-rus', 'rus-eng']:
                        direction = UserCardDirection.query.filter_by(
                            user_word_id=user_word.id,
                            direction=direction_str
                        ).first()

                        if not direction:
                            direction = UserCardDirection(user_word_id=user_word.id, direction=direction_str)
                            db.session.add(direction)
                            db.session.flush()

                        direction.update_after_review(quality)

            except (IntegrityError, OperationalError) as e:
                srs_errors.append(f'word_id={word_id}: {e}')
                logger.exception('SRS update failed for word %s in matching game: %s', word_id, e)
            except Exception as e:
                srs_errors.append(f'word_id={word_id}: {e}')
                logger.exception('Unexpected error in SRS update for word %s in matching game: %s', word_id, e)

        if srs_errors:
            logger.warning(f'Matching game SRS update had {len(srs_errors)} errors out of {len(word_ids)} words')

        db.session.commit()

    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.words_studied = total_pairs
            session.correct_answers = pairs_matched
            session.complete_session()
            db.session.commit()
            logger.info(
                'study_session_complete user=%s session=%s session_type=%s duration=%s words_studied=%s',
                current_user.id, session.id, session.session_type, session.duration, session.words_studied
            )

    try:
        game_score = GameScore(
            user_id=current_user.id,
            game_type='matching',
            difficulty=difficulty,
            score=score,
            time_taken=time_taken,
            pairs_matched=pairs_matched,
            total_pairs=total_pairs,
            moves=moves,
            date_achieved=datetime.now(timezone.utc)
        )

        db.session.add(game_score)
        db.session.commit()

        rank = game_score.get_rank()

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
            'game_score_id': game_score.id,
            'xp_earned': xp_award.xp_awarded if xp_award else 0,
            'total_xp': _matching_total_xp,
            'level': _matching_level
        })
    except Exception as e:
        logger.exception('Error saving matching game score: %s', e)
        db.session.rollback()

        return jsonify({
            'success': False,
            'error': 'Внутренняя ошибка сервера'
        }), 500


@study.route('/api/complete-quiz', methods=['POST'])
@login_required
def complete_quiz():
    from app.study.models import QuizDeck, QuizResult
    from app.study.xp_service import XPService

    if not request.is_json:
        return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 415
    data = request.json or {}
    session_id = data.get('session_id')
    deck_id = data.get('deck_id')
    source = data.get('source')
    plan_from = data.get('from')
    plan_slot = data.get('slot')
    score = data.get('score', 0)
    total_questions = data.get('total_questions', 0)
    correct_answers = data.get('correct_answers', 0)
    time_taken = data.get('time_taken', 0)
    has_streak = data.get('has_streak', False)

    if session_id:
        session = StudySession.query.get(session_id)
        if session and session.user_id == current_user.id:
            session.complete_session()
            logger.info(
                'study_session_complete user=%s session=%s session_type=%s duration=%s words_studied=%s',
                current_user.id, session.id, session.session_type, session.duration, session.words_studied
            )

    if deck_id:
        deck = QuizDeck.query.get(deck_id)
        if deck:
            quiz_result = QuizResult(
                deck_id=deck_id,
                user_id=current_user.id,
                total_questions=total_questions,
                correct_answers=correct_answers,
                score_percentage=score,
                time_taken=time_taken
            )
            db.session.add(quiz_result)

            deck.average_score = db.session.query(func.avg(QuizResult.score_percentage)).filter(
                QuizResult.deck_id == deck_id
            ).scalar() or 0

            db.session.commit()

    game_score = GameScore(
        user_id=current_user.id,
        game_type='quiz',
        score=score,
        time_taken=time_taken,
        correct_answers=correct_answers,
        total_questions=total_questions,
        date_achieved=datetime.now(timezone.utc)
    )
    db.session.add(game_score)
    db.session.commit()

    xp_breakdown = XPService.calculate_quiz_xp(
        correct_answers=correct_answers,
        total_questions=total_questions,
        time_taken=time_taken,
        has_streak=has_streak
    )

    from app.achievements.xp_service import award_game_xp_idempotent, get_level_info
    from app.achievements.models import UserStatistics as _UserStats
    xp_award = None
    if xp_breakdown['total_xp'] > 0:
        xp_award = award_game_xp_idempotent(
            current_user.id,
            int(session_id) if session_id else None,
            'quiz',
            xp_breakdown['total_xp'],
            datetime.now(timezone.utc).date(),
        )
        db.session.commit()

    if (
        source == LINEAR_PLAN_DECK_QUIZ_SOURCE
        and plan_from == 'linear_plan'
        and plan_slot == 'srs'
        and int(total_questions or 0) > 0
    ):
        try:
            from app.daily_plan.linear.xp import (
                maybe_award_linear_perfect_day,
                maybe_award_srs_global_xp,
            )
            if maybe_award_srs_global_xp(current_user.id, db_session=db) is not None:
                maybe_award_linear_perfect_day(current_user.id, db_session=db)
                db.session.commit()
        except Exception:
            logger.warning(
                'linear_xp: deck quiz award failed user=%s',
                current_user.id,
                exc_info=True,
            )
            db.session.rollback()

    quiz_data = {
        'score': score,
        'total_questions': total_questions,
        'correct_answers': correct_answers,
        'time_taken': time_taken,
        'has_streak': has_streak
    }
    newly_earned = XPService.check_quiz_achievements(current_user.id, quiz_data)

    _quiz_stats = _UserStats.query.filter_by(user_id=current_user.id).first()
    _quiz_total_xp = int(_quiz_stats.total_xp or 0) if _quiz_stats else 0
    _quiz_level = get_level_info(_quiz_total_xp).current_level

    achievements_list = [
        {
            'code': ach.code,
            'name': ach.name,
            'description': ach.description,
            'icon': ach.icon,
            'xp_reward': ach.xp_reward
        }
        for ach in newly_earned if ach is not None
    ] if newly_earned else []

    return jsonify({
        'success': True,
        'score': score,
        'xp_earned': xp_award.xp_awarded if xp_award else 0,
        'xp_breakdown': xp_breakdown,
        'total_xp': _quiz_total_xp,
        'level': _quiz_level,
        'achievements': achievements_list
    })


@study.route('/api/leaderboard/<game_type>')
@login_required
def get_leaderboard(game_type):
    difficulty = request.args.get('difficulty')
    limit = min(int(request.args.get('limit', 10)), 50)

    leaderboard_entries = GameScore.get_leaderboard(game_type, difficulty, limit)

    leaderboard_data = []
    for i, entry in enumerate(leaderboard_entries):
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
