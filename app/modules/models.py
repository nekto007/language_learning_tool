from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Index, JSON
from sqlalchemy.orm import relationship

from app.utils.db import db


class SystemModule(db.Model):
    """
    Модель для представления модулей приложения.
    Модули - это отдельные функциональные разделы (curriculum, books, words и т.д.)
    """
    __tablename__ = 'system_modules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)  # Уникальный код модуля: 'curriculum', 'books', 'words'
    name = Column(String(100), nullable=False)  # Название для отображения: 'Учебная программа', 'Книги'
    description = Column(Text)  # Описание модуля
    icon = Column(String(50))  # Иконка для UI (например, 'book', 'graduation-cap')
    is_active = Column(Boolean, default=True)  # Активен ли модуль глобально
    is_default = Column(Boolean, default=False)  # Подключается ли автоматически при регистрации
    order = Column(Integer, default=0)  # Порядок отображения в навигации
    blueprint_name = Column(String(50))  # Название blueprint для динамической регистрации
    url_prefix = Column(String(100))  # URL префикс для модуля
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Связь с пользователями
    user_modules = relationship('UserModule', back_populates='module', cascade='all, delete-orphan')

    __table_args__ = (
        Index('idx_module_code', 'code'),
        Index('idx_module_active', 'is_active'),
        Index('idx_module_order', 'order'),
    )

    def __repr__(self):
        return f'<SystemModule {self.code}: {self.name}>'

    def to_dict(self):
        """Преобразует модель в словарь для API"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'icon': self.icon,
            'is_active': self.is_active,
            'is_default': self.is_default,
            'order': self.order,
            'blueprint_name': self.blueprint_name,
            'url_prefix': self.url_prefix,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class UserModule(db.Model):
    """
    Модель для связи пользователей с модулями.
    Определяет, какие модули доступны каждому пользователю.
    """
    __tablename__ = 'user_modules'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    module_id = Column(Integer, ForeignKey('system_modules.id', ondelete='CASCADE'), nullable=False)
    is_enabled = Column(Boolean, default=True)  # Включен ли модуль для данного пользователя
    granted_by_admin = Column(Boolean, default=False)  # Выдан ли модуль админом вручную
    granted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # Дата выдачи модуля
    settings = Column(JSON)  # JSON настройки модуля для данного пользователя
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Связи
    user = relationship('User', backref='user_modules')
    module = relationship('SystemModule', back_populates='user_modules')

    __table_args__ = (
        Index('idx_user_module_user_id', 'user_id'),
        Index('idx_user_module_module_id', 'module_id'),
        Index('idx_user_module_enabled', 'is_enabled'),
        # Уникальный индекс: один пользователь не может иметь дубликат одного модуля
        Index('idx_user_module_unique', 'user_id', 'module_id', unique=True),
    )

    def __repr__(self):
        return f'<UserModule user_id={self.user_id} module_id={self.module_id}>'

    def to_dict(self):
        """Преобразует модель в словарь для API"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'module_id': self.module_id,
            'module_code': self.module.code if self.module else None,
            'module_name': self.module.name if self.module else None,
            'is_enabled': self.is_enabled,
            'granted_by_admin': self.granted_by_admin,
            'granted_at': self.granted_at.isoformat() if self.granted_at else None,
            'settings': self.settings,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
