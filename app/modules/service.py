from typing import List, Optional
from flask_login import current_user
from sqlalchemy import and_

from app.utils.db import db
from app.modules.models import SystemModule, UserModule


class ModuleService:
    """Сервис для работы с модулями"""

    @staticmethod
    def get_all_modules() -> List[SystemModule]:
        """Получить все модули"""
        return SystemModule.query.order_by(SystemModule.order).all()

    @staticmethod
    def get_active_modules() -> List[SystemModule]:
        """Получить все активные модули"""
        return SystemModule.query.filter_by(is_active=True).order_by(SystemModule.order).all()

    @staticmethod
    def get_module_by_code(code: str) -> Optional[SystemModule]:
        """Получить модуль по коду"""
        return SystemModule.query.filter_by(code=code).first()

    @staticmethod
    def get_module_by_id(module_id: int) -> Optional[SystemModule]:
        """Получить модуль по ID"""
        return SystemModule.query.get(module_id)

    @staticmethod
    def get_default_modules() -> List[SystemModule]:
        """Получить модули, которые подключаются по умолчанию"""
        return SystemModule.query.filter_by(is_default=True, is_active=True).all()

    @staticmethod
    def get_user_modules(user_id: int, enabled_only: bool = True) -> List[SystemModule]:
        """
        Получить модули пользователя

        Args:
            user_id: ID пользователя
            enabled_only: Вернуть только включенные модули
        """
        query = db.session.query(SystemModule).join(UserModule).filter(
            UserModule.user_id == user_id
        )

        if enabled_only:
            query = query.filter(UserModule.is_enabled == True)

        return query.order_by(SystemModule.order).all()

    @staticmethod
    def get_user_enabled_module_codes(user_id: int) -> List[str]:
        """
        Получить коды включенных модулей пользователя

        Args:
            user_id: ID пользователя

        Returns:
            Список кодов модулей
        """
        modules = ModuleService.get_user_modules(user_id, enabled_only=True)
        return [module.code for module in modules]

    @staticmethod
    def is_module_enabled_for_user(user_id: int, module_code: str) -> bool:
        """
        Проверить, включен ли модуль для пользователя

        Args:
            user_id: ID пользователя
            module_code: Код модуля
        """
        module = ModuleService.get_module_by_code(module_code)
        if not module or not module.is_active:
            return False

        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module.id
        ).first()

        return user_module is not None and user_module.is_enabled

    @staticmethod
    def grant_module_to_user(user_id: int, module_id: int, granted_by_admin: bool = False) -> UserModule:
        """
        Выдать модуль пользователю

        Args:
            user_id: ID пользователя
            module_id: ID модуля
            granted_by_admin: Выдан ли модуль админом

        Returns:
            Объект UserModule
        """
        # Проверяем, не выдан ли уже модуль
        existing = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module_id
        ).first()

        if existing:
            # Если модуль уже есть, просто включаем его
            existing.is_enabled = True
            existing.granted_by_admin = granted_by_admin or existing.granted_by_admin
            db.session.commit()
            return existing

        # Создаем новый UserModule
        user_module = UserModule(
            user_id=user_id,
            module_id=module_id,
            is_enabled=True,
            granted_by_admin=granted_by_admin
        )
        db.session.add(user_module)
        db.session.commit()
        return user_module

    @staticmethod
    def revoke_module_from_user(user_id: int, module_id: int) -> bool:
        """
        Отозвать модуль у пользователя

        Args:
            user_id: ID пользователя
            module_id: ID модуля

        Returns:
            True если модуль был отозван, False если не найден
        """
        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module_id
        ).first()

        if user_module:
            user_module.is_enabled = False
            db.session.commit()
            return True
        return False

    @staticmethod
    def toggle_module_for_user(user_id: int, module_id: int) -> bool:
        """
        Переключить состояние модуля для пользователя

        Args:
            user_id: ID пользователя
            module_id: ID модуля

        Returns:
            Новое состояние модуля (True/False)
        """
        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module_id
        ).first()

        if user_module:
            user_module.is_enabled = not user_module.is_enabled
            db.session.commit()
            return user_module.is_enabled
        else:
            # Если модуль не найден, выдаем его
            ModuleService.grant_module_to_user(user_id, module_id)
            return True

    @staticmethod
    def grant_default_modules_to_user(user_id: int):
        """
        Выдать пользователю все дефолтные модули

        Args:
            user_id: ID пользователя
        """
        default_modules = ModuleService.get_default_modules()
        for module in default_modules:
            ModuleService.grant_module_to_user(user_id, module.id, granted_by_admin=False)

    @staticmethod
    def grant_modules_to_users(module_id: int, user_ids: List[int], granted_by_admin: bool = True):
        """
        Массовая выдача модуля группе пользователей

        Args:
            module_id: ID модуля
            user_ids: Список ID пользователей
            granted_by_admin: Выдан ли модуль админом
        """
        for user_id in user_ids:
            ModuleService.grant_module_to_user(user_id, module_id, granted_by_admin)

    @staticmethod
    def get_module_statistics() -> dict:
        """
        Получить статистику использования модулей

        Returns:
            Словарь со статистикой по каждому модулю
        """
        modules = ModuleService.get_all_modules()
        stats = {}

        for module in modules:
            total_users = UserModule.query.filter_by(module_id=module.id).count()
            enabled_users = UserModule.query.filter_by(
                module_id=module.id,
                is_enabled=True
            ).count()
            granted_by_admin = UserModule.query.filter_by(
                module_id=module.id,
                granted_by_admin=True
            ).count()

            stats[module.code] = {
                'module_id': module.id,
                'name': module.name,
                'total_users': total_users,
                'enabled_users': enabled_users,
                'granted_by_admin': granted_by_admin,
                'is_active': module.is_active,
                'is_default': module.is_default
            }

        return stats

    @staticmethod
    def create_module(code: str, name: str, **kwargs) -> SystemModule:
        """
        Создать новый модуль

        Args:
            code: Уникальный код модуля
            name: Название модуля
            **kwargs: Дополнительные параметры

        Returns:
            Созданный модуль
        """
        module = SystemModule(code=code, name=name, **kwargs)
        db.session.add(module)
        db.session.commit()
        return module

    @staticmethod
    def update_module(module_id: int, **kwargs) -> Optional[SystemModule]:
        """
        Обновить модуль

        Args:
            module_id: ID модуля
            **kwargs: Параметры для обновления

        Returns:
            Обновленный модуль или None
        """
        module = SystemModule.query.get(module_id)
        if not module:
            return None

        for key, value in kwargs.items():
            if hasattr(module, key):
                setattr(module, key, value)

        db.session.commit()
        return module

    @staticmethod
    def delete_module(module_id: int) -> bool:
        """
        Удалить модуль

        Args:
            module_id: ID модуля

        Returns:
            True если модуль удален, False если не найден
        """
        module = SystemModule.query.get(module_id)
        if not module:
            return False

        db.session.delete(module)
        db.session.commit()
        return True

    @staticmethod
    def get_user_module_settings(user_id: int, module_code: str) -> Optional[dict]:
        """
        Получить настройки модуля для пользователя

        Args:
            user_id: ID пользователя
            module_code: Код модуля

        Returns:
            Настройки модуля или None
        """
        module = ModuleService.get_module_by_code(module_code)
        if not module:
            return None

        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module.id
        ).first()

        return user_module.settings if user_module else None

    @staticmethod
    def update_user_module_settings(user_id: int, module_code: str, settings: dict) -> bool:
        """
        Обновить настройки модуля для пользователя

        Args:
            user_id: ID пользователя
            module_code: Код модуля
            settings: Новые настройки

        Returns:
            True если настройки обновлены, False если модуль не найден
        """
        module = ModuleService.get_module_by_code(module_code)
        if not module:
            return False

        user_module = UserModule.query.filter_by(
            user_id=user_id,
            module_id=module.id
        ).first()

        if not user_module:
            return False

        user_module.settings = settings
        db.session.commit()
        return True
