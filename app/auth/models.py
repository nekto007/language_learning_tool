import secrets
import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, desc
from sqlalchemy.orm import relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.utils.db import db


def _generate_referral_code() -> str:
    """Generate a short unique referral code."""
    return uuid.uuid4().hex[:8]


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(120), unique=True)
    password_hash = Column(Text, nullable=False)
    salt = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime)
    active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    onboarding_completed = Column(Boolean, default=False, nullable=False, server_default='false')
    onboarding_level = Column(String(4), nullable=True)  # CEFR level chosen during onboarding (A0-C2)
    onboarding_focus = Column(String(100), nullable=True)  # Study focus chosen during onboarding

    # Referral system
    referral_code = Column(String(16), unique=True, nullable=True, default=_generate_referral_code)
    referred_by_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    # Default deck for adding words to study (null = "только в изучение")
    default_study_deck_id = Column(Integer, ForeignKey('quiz_decks.id', ondelete='SET NULL'), nullable=True)

    # Email unsubscribe
    email_unsubscribe_token = Column(String(64), nullable=True, unique=True)
    email_opted_out = Column(Boolean, default=False, nullable=False)

    referred_by = relationship('User', remote_side='User.id', foreign_keys=[referred_by_id])

    __table_args__ = (
        Index('idx_user_username', 'username'),
        Index('idx_user_email', 'email'),
    )

    def ensure_referral_code(self) -> str:
        """Generate a referral code if not set, and return it."""
        if not self.referral_code:
            self.referral_code = secrets.token_urlsafe(8)[:12]
            db.session.commit()
        return self.referral_code

    def set_password(self, password):
        self.salt = secrets.token_hex(16)
        self.password_hash = generate_password_hash(password + self.salt)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password + self.salt)

    def get_word_status(self, word_id):
        """
        Получает статус слова для пользователя.
        Возвращает целое число для API совместимости:
        0 = новое, 1 = изучаемое, 2 = на повторении, 3 = изучено
        """
        from app.study.models import UserWord
        from app.utils.db import string_to_status

        user_word = UserWord.query.filter_by(
            user_id=self.id,
            word_id=word_id
        ).first()

        if user_word:
            return string_to_status(user_word.status)
        return 0

    def set_word_status(self, word_id, status):
        """
        Добавляет или удаляет слово из изучения.

        status:
            0 = удалить из изучения (удаляет UserWord и направления)
            1 = добавить к изучению (статус 'new')
            2 = на повторении ('review')
            3 = уже знаю ('review' с высоким интервалом 180+ дней)
        """
        from datetime import datetime, timezone, timedelta
        from app.study.models import UserWord, UserCardDirection
        from app.utils.db import db

        # Маппинг числовых статусов в строковые
        # status=3 теперь ставит 'review' вместо 'mastered'
        status_map = {
            1: 'new',
            2: 'review',
            3: 'review'  # "Уже знаю" = review с высоким интервалом
        }

        user_word = UserWord.query.filter_by(user_id=self.id, word_id=word_id).first()

        # Если статус 0 и запись существует, удаляем её
        if status == 0 and user_word:
            # Удаляем связанные направления
            UserCardDirection.query.filter_by(user_word_id=user_word.id).delete()
            # Удаляем запись UserWord
            db.session.delete(user_word)
            db.session.commit()
            return None

        # Определяем строковый статус
        str_status = status_map.get(status, 'new')

        # Определяем, нужно ли ставить высокий интервал (для "Уже знаю")
        is_already_known = (status == 3)
        now = datetime.now(timezone.utc)

        # Создаём новую запись, если её нет
        if not user_word and status > 0:
            user_word = UserWord(user_id=self.id, word_id=word_id)
            user_word.status = str_status
            db.session.add(user_word)
            db.session.flush()  # Чтобы получить ID

            from app.study.deck_utils import ensure_word_in_default_deck
            ensure_word_in_default_deck(self.id, word_id, user_word.id)

            # Создаём направления для слова
            for direction_str in ['eng-rus', 'rus-eng']:
                direction = UserCardDirection(
                    user_word_id=user_word.id,
                    direction=direction_str
                )
                # Для "Уже знаю" - ставим высокий интервал и статус review
                if is_already_known:
                    direction.state = 'review'
                    direction.interval = UserWord.MASTERED_THRESHOLD_DAYS  # 180 дней
                    direction.ease_factor = 2.5
                    direction.repetitions = 10  # Имитируем много успешных повторов
                    direction.next_review = now + timedelta(days=UserWord.MASTERED_THRESHOLD_DAYS)
                    direction.first_reviewed = now
                    direction.last_reviewed = now
                db.session.add(direction)
        elif user_word and status > 0:
            # Обновляем статус существующей записи
            user_word.status = str_status

            # Для "Уже знаю" - обновляем интервалы на карточках
            if is_already_known:
                directions = UserCardDirection.query.filter_by(user_word_id=user_word.id).all()
                for direction in directions:
                    direction.state = 'review'
                    direction.interval = UserWord.MASTERED_THRESHOLD_DAYS
                    direction.ease_factor = max(direction.ease_factor, 2.5)
                    direction.repetitions = max(direction.repetitions, 10)
                    direction.next_review = now + timedelta(days=UserWord.MASTERED_THRESHOLD_DAYS)
                    if not direction.first_reviewed:
                        direction.first_reviewed = now
                    direction.last_reviewed = now

        # Пересчитываем статус UserWord на основе состояний карточек
        if user_word:
            db.session.flush()  # Flush card state changes so recalculate_status() sees them
            user_word.recalculate_status()

        db.session.commit()
        return user_word

    def get_recent_reading_progress(self, limit=3):
        """Get recent chapter reading progress"""
        from app.books.models import UserChapterProgress
        return UserChapterProgress.query.filter_by(
            user_id=self.id
        ).order_by(desc(UserChapterProgress.updated_at)).limit(limit).all()

    def get_last_read_book(self):
        """Get last read book from chapter progress"""
        from sqlalchemy.orm import joinedload
        from app.books.models import UserChapterProgress, Chapter, Book
        latest_progress = UserChapterProgress.query.filter_by(
            user_id=self.id
        ).join(Chapter).join(Book).options(
            joinedload(UserChapterProgress.chapter).joinedload(Chapter.book)
        ).order_by(
            desc(UserChapterProgress.updated_at)
        ).first()
        return latest_progress.chapter.book if latest_progress else None

    def get_reading_progress_count(self):
        """Get count of books with reading progress"""
        from app.books.models import UserChapterProgress, Chapter, Book
        return db.session.query(Book.id).join(Chapter).join(
            UserChapterProgress
        ).filter(UserChapterProgress.user_id == self.id).distinct().count()

    @property
    def is_active(self):
        return self.active

    def get_id(self):
        return str(self.id)
    
    def __repr__(self):
        return f'<User {self.username}>'


class ReferralLog(db.Model):
    __tablename__ = 'referral_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    referred_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    referrer = relationship('User', foreign_keys=[referrer_id], backref='referrals_made')
    referred = relationship('User', foreign_keys=[referred_id], backref='referred_by')

    __table_args__ = (
        Index('idx_referral_referrer', 'referrer_id'),
    )

    def __repr__(self):
        return f'<ReferralLog referrer={self.referrer_id} referred={self.referred_id}>'
