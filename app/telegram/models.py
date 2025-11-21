"""
Telegram API Token models

SECURITY: Implements proper token management with:
- Expiration dates
- Scope-based permissions
- Token revocation
- Audit trail (created_at, last_used_at)
"""
import secrets
from datetime import datetime, timedelta, timezone
from app.utils.db import db


class TelegramToken(db.Model):
    """
    Telegram API token with expiration and scope

    SECURITY IMPROVEMENTS:
    - Tokens expire after 90 days (configurable)
    - Each token has specific scope (read, write, admin)
    - Tokens can be revoked without changing user password
    - Audit trail: created_at, last_used_at, revoked_at
    - Multiple tokens per user (e.g., different devices)
    """
    __tablename__ = 'telegram_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Token value (hashed or encrypted in production)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Scope defines what this token can access
    # Possible values: 'read', 'write', 'admin', 'read,write'
    scope = db.Column(db.String(100), default='read', nullable=False)

    # Token lifecycle
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime)

    # Revocation
    revoked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime)
    revoked_reason = db.Column(db.String(255))

    # Optional: Device/client info for tracking
    device_name = db.Column(db.String(100))
    user_agent = db.Column(db.String(255))

    # Relationships
    user = db.relationship('User', backref=db.backref('telegram_tokens', lazy='dynamic'))

    def __repr__(self):
        return f'<TelegramToken {self.id} user={self.user_id} scope={self.scope} revoked={self.revoked}>'

    @staticmethod
    def generate_token():
        """
        Generate a cryptographically secure random token

        Returns:
            str: 64-character hexadecimal token
        """
        return secrets.token_hex(32)  # 32 bytes = 64 hex characters

    @classmethod
    def create_token(cls, user_id, scope='read', expires_in_days=90, device_name=None, user_agent=None):
        """
        Create a new Telegram API token

        Args:
            user_id: User ID
            scope: Token scope (comma-separated: 'read', 'write', 'admin')
            expires_in_days: Token expiration in days (default: 90)
            device_name: Optional device identifier
            user_agent: Optional user agent string

        Returns:
            TelegramToken: New token instance
        """
        token_value = cls.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        token = cls(
            user_id=user_id,
            token=token_value,
            scope=scope,
            expires_at=expires_at,
            device_name=device_name,
            user_agent=user_agent
        )

        db.session.add(token)
        db.session.commit()

        return token

    def is_valid(self):
        """
        Check if token is valid (not expired, not revoked)

        Returns:
            bool: True if token is valid
        """
        if self.revoked:
            return False

        # Ensure expires_at is timezone-aware for comparison
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            return False

        return True

    def has_scope(self, required_scope):
        """
        Check if token has required scope

        Args:
            required_scope: Required scope (e.g., 'read', 'write', 'admin')

        Returns:
            bool: True if token has required scope
        """
        if not self.is_valid():
            return False

        # Admin scope has all permissions
        if 'admin' in self.scope:
            return True

        # Check if required scope is in token's scope
        token_scopes = set(self.scope.split(','))
        return required_scope in token_scopes

    def revoke(self, reason=None):
        """
        Revoke this token

        Args:
            reason: Optional reason for revocation
        """
        self.revoked = True
        self.revoked_at = datetime.now(timezone.utc)
        self.revoked_reason = reason
        db.session.commit()

    def update_last_used(self):
        """Update last_used_at timestamp"""
        self.last_used_at = datetime.now(timezone.utc)
        db.session.commit()

    @classmethod
    def get_valid_token(cls, token_value):
        """
        Get valid token by value

        Args:
            token_value: Token string

        Returns:
            TelegramToken or None: Valid token or None if invalid/not found
        """
        token = cls.query.filter_by(token=token_value).first()

        if token and token.is_valid():
            token.update_last_used()
            return token

        return None

    @classmethod
    def revoke_all_user_tokens(cls, user_id, reason=None):
        """
        Revoke all tokens for a user

        Args:
            user_id: User ID
            reason: Optional reason for revocation
        """
        tokens = cls.query.filter_by(user_id=user_id, revoked=False).all()
        for token in tokens:
            token.revoke(reason)

    @classmethod
    def cleanup_expired_tokens(cls, days_old=30):
        """
        Delete expired tokens older than specified days

        Args:
            days_old: Delete tokens expired more than this many days ago
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
        cls.query.filter(
            cls.expires_at < cutoff_date,
            cls.revoked == True
        ).delete()
        db.session.commit()