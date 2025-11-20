"""
Session Service - study session tracking

Responsibilities:
- Session lifecycle (start, complete)
- XP tracking
- Session statistics
"""
from typing import Dict, Optional
from datetime import datetime, timezone

from app.utils.db import db
from app.study.models import StudySession, UserXP


class SessionService:
    """Service for managing study sessions"""

    @staticmethod
    def start_session(user_id: int, session_type: str) -> StudySession:
        """
        Start a new study session

        Args:
            user_id: User ID
            session_type: Type of session ('cards', 'quiz', 'matching')

        Returns:
            Created StudySession object
        """
        session = StudySession(
            user_id=user_id,
            session_type=session_type,
            start_time=datetime.now(timezone.utc)
        )
        db.session.add(session)
        db.session.commit()
        return session

    @staticmethod
    def complete_session(session_id: int, words_studied: int = 0,
                        correct_answers: int = 0, incorrect_answers: int = 0) -> Optional[StudySession]:
        """
        Complete a study session

        Args:
            session_id: Session ID
            words_studied: Number of words studied
            correct_answers: Number of correct answers
            incorrect_answers: Number of incorrect answers

        Returns:
            Updated StudySession object or None if not found
        """
        session = StudySession.query.get(session_id)
        if not session:
            return None

        session.end_time = datetime.now(timezone.utc)
        session.words_studied = words_studied
        session.correct_answers = correct_answers
        session.incorrect_answers = incorrect_answers

        db.session.commit()
        return session

    @staticmethod
    def award_xp(user_id: int, amount: int, source: str, source_id: int = None) -> UserXP:
        """
        Award XP to user

        Args:
            user_id: User ID
            amount: XP amount to award
            source: XP source ('lesson', 'quiz', 'cards', 'achievement')
            source_id: Optional ID of the source (lesson_id, quiz_id, etc.)

        Returns:
            Created UserXP record
        """
        xp_record = UserXP(
            user_id=user_id,
            xp_amount=amount,
            source=source,
            source_id=source_id,
            earned_at=datetime.now(timezone.utc)
        )
        db.session.add(xp_record)
        db.session.commit()
        return xp_record

    @staticmethod
    def get_user_total_xp(user_id: int) -> int:
        """Get total XP for user"""
        from sqlalchemy import func
        total = db.session.query(func.sum(UserXP.xp_amount)).filter(
            UserXP.user_id == user_id
        ).scalar()
        return total or 0

    @staticmethod
    def get_session_stats(user_id: int, days: int = 7) -> Dict:
        """
        Get session statistics for user

        Args:
            user_id: User ID
            days: Number of days to look back

        Returns:
            Dictionary with session statistics
        """
        from datetime import timedelta
        from sqlalchemy import func

        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        sessions = StudySession.query.filter(
            StudySession.user_id == user_id,
            StudySession.start_time >= start_date,
            StudySession.end_time.isnot(None)
        ).all()

        total_sessions = len(sessions)
        total_words = sum(s.words_studied for s in sessions)
        total_correct = sum(s.correct_answers for s in sessions)
        total_incorrect = sum(s.incorrect_answers for s in sessions)
        total_time = sum(
            (s.end_time - s.start_time).total_seconds()
            for s in sessions if s.end_time
        )

        accuracy = (total_correct / (total_correct + total_incorrect) * 100
                   if (total_correct + total_incorrect) > 0 else 0)

        return {
            'period_days': days,
            'total_sessions': total_sessions,
            'total_words_studied': total_words,
            'total_correct': total_correct,
            'total_incorrect': total_incorrect,
            'accuracy_percent': round(accuracy, 1),
            'total_time_seconds': int(total_time),
            'avg_session_time_seconds': int(total_time / total_sessions) if total_sessions > 0 else 0
        }
