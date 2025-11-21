"""
Tests for modules service
Тесты сервиса модулей
"""
import pytest
from app.modules.service import ModuleService
from app.modules.models import SystemModule, UserModule


def create_test_module(code, name, **kwargs):
    """Helper function to create a test module with required fields"""
    defaults = {
        'order': 1,
        'is_active': True,
        'blueprint_name': code,  # Use code as blueprint_name by default
        'url_prefix': f'/{code}'  # Use /code as url_prefix by default
    }
    defaults.update(kwargs)
    return SystemModule(code=code, name=name, **defaults)


class TestGetAllModules:
    """Тесты метода get_all_modules"""

    def test_get_all_modules_returns_all(self, app, db_session):
        """Тест возврата всех модулей"""
        with app.app_context():
            # Create modules
            module1 = create_test_module('test1', 'Test 1', order=2)
            module2 = create_test_module('test2', 'Test 2', order=1, is_active=False)
            db_session.add_all([module1, module2])
            db_session.commit()

            modules = ModuleService.get_all_modules()

            assert len(modules) >= 2
            # Should be ordered by order field
            codes = [m.code for m in modules]
            assert codes.index('test2') < codes.index('test1')

    def test_get_all_modules_ordered(self, app, db_session):
        """Тест что модули отсортированы по полю order"""
        with app.app_context():
            module1 = create_test_module('order_test1', 'Order 1', order=5)
            module2 = create_test_module('order_test2', 'Order 2', order=1)
            module3 = create_test_module('order_test3', 'Order 3', order=3)
            db_session.add_all([module1, module2, module3])
            db_session.commit()

            modules = ModuleService.get_all_modules()

            # Filter to our test modules
            test_modules = [m for m in modules if m.code.startswith('order_test')]
            assert test_modules[0].order == 1
            assert test_modules[1].order == 3
            assert test_modules[2].order == 5


class TestGetActiveModules:
    """Тесты метода get_active_modules"""

    def test_get_active_modules_only_active(self, app, db_session):
        """Тест возврата только активных модулей"""
        with app.app_context():
            module1 = create_test_module('active_test1', 'Active')
            module2 = create_test_module('inactive_test', 'Inactive', order=2, is_active=False)
            db_session.add_all([module1, module2])
            db_session.commit()

            modules = ModuleService.get_active_modules()

            codes = [m.code for m in modules]
            assert 'active_test1' in codes
            assert 'inactive_test' not in codes


class TestGetModuleByCode:
    """Тесты метода get_module_by_code"""

    def test_get_module_by_code_exists(self, app, db_session):
        """Тест получения модуля по коду когда он существует"""
        with app.app_context():
            module = create_test_module('code_test1', 'Test')
            db_session.add(module)
            db_session.commit()

            result = ModuleService.get_module_by_code('code_test1')

            assert result is not None
            assert result.code == 'code_test1'
            assert result.name == 'Test'

    def test_get_module_by_code_not_exists(self, app, db_session):
        """Тест получения несуществующего модуля"""
        with app.app_context():
            result = ModuleService.get_module_by_code('nonexistent_code_xyz')

            assert result is None


class TestGetModuleById:
    """Тесты метода get_module_by_id"""

    def test_get_module_by_id_exists(self, app, db_session):
        """Тест получения модуля по ID когда он существует"""
        with app.app_context():
            module = create_test_module('id_test1', 'Test')
            db_session.add(module)
            db_session.commit()

            result = ModuleService.get_module_by_id(module.id)

            assert result is not None
            assert result.id == module.id

    def test_get_module_by_id_not_exists(self, app, db_session):
        """Тест получения несуществующего модуля"""
        with app.app_context():
            result = ModuleService.get_module_by_id(999999)

            assert result is None


class TestGetDefaultModules:
    """Тесты метода get_default_modules"""

    def test_get_default_modules_only_default_and_active(self, app, db_session):
        """Тест возврата только дефолтных и активных модулей"""
        with app.app_context():
            module1 = create_test_module('default_active', 'Default Active', is_default=True)
            module2 = create_test_module('default_inactive', 'Default Inactive',
                                        order=2, is_active=False, is_default=True)
            module3 = create_test_module('not_default', 'Not Default',
                                        order=3, is_default=False)
            db_session.add_all([module1, module2, module3])
            db_session.commit()

            modules = ModuleService.get_default_modules()

            codes = [m.code for m in modules]
            assert 'default_active' in codes
            assert 'default_inactive' not in codes  # Inactive
            assert 'not_default' not in codes  # Not default


class TestGetUserModules:
    """Тесты метода get_user_modules"""

    def test_get_user_modules_enabled_only(self, app, db_session, test_user):
        """Тест получения только включенных модулей"""
        with app.app_context():
            module1 = create_test_module('user_enabled', 'Enabled')
            module2 = create_test_module('user_disabled', 'Disabled', order=2)
            db_session.add_all([module1, module2])
            db_session.commit()

            user_module1 = UserModule(user_id=test_user.id, module_id=module1.id, is_enabled=True)
            user_module2 = UserModule(user_id=test_user.id, module_id=module2.id, is_enabled=False)
            db_session.add_all([user_module1, user_module2])
            db_session.commit()

            modules = ModuleService.get_user_modules(test_user.id, enabled_only=True)

            codes = [m.code for m in modules]
            assert 'user_enabled' in codes
            assert 'user_disabled' not in codes

    def test_get_user_modules_all(self, app, db_session, test_user):
        """Тест получения всех модулей пользователя"""
        with app.app_context():
            module1 = create_test_module('user_all1', 'All 1')
            module2 = create_test_module('user_all2', 'All 2', order=2)
            db_session.add_all([module1, module2])
            db_session.commit()

            user_module1 = UserModule(user_id=test_user.id, module_id=module1.id, is_enabled=True)
            user_module2 = UserModule(user_id=test_user.id, module_id=module2.id, is_enabled=False)
            db_session.add_all([user_module1, user_module2])
            db_session.commit()

            modules = ModuleService.get_user_modules(test_user.id, enabled_only=False)

            codes = [m.code for m in modules]
            assert 'user_all1' in codes
            assert 'user_all2' in codes


class TestGetUserEnabledModuleCodes:
    """Тесты метода get_user_enabled_module_codes"""

    def test_get_user_enabled_module_codes(self, app, db_session, test_user):
        """Тест получения кодов включенных модулей"""
        with app.app_context():
            module1 = create_test_module('enabled_code1', 'Code 1')
            module2 = create_test_module('enabled_code2', 'Code 2', order=2)
            db_session.add_all([module1, module2])
            db_session.commit()

            user_module1 = UserModule(user_id=test_user.id, module_id=module1.id, is_enabled=True)
            user_module2 = UserModule(user_id=test_user.id, module_id=module2.id, is_enabled=False)
            db_session.add_all([user_module1, user_module2])
            db_session.commit()

            codes = ModuleService.get_user_enabled_module_codes(test_user.id)

            assert 'enabled_code1' in codes
            assert 'enabled_code2' not in codes


class TestIsModuleEnabledForUser:
    """Тесты метода is_module_enabled_for_user"""

    def test_is_module_enabled_for_user_true(self, app, db_session, test_user):
        """Тест когда модуль включен для пользователя"""
        with app.app_context():
            module = create_test_module('enabled_check', 'Check')
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=True)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.is_module_enabled_for_user(test_user.id, 'enabled_check')

            assert result is True

    def test_is_module_enabled_for_user_false_disabled(self, app, db_session, test_user):
        """Тест когда модуль отключен для пользователя"""
        with app.app_context():
            module = create_test_module('disabled_check', 'Check')
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=False)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.is_module_enabled_for_user(test_user.id, 'disabled_check')

            assert result is False

    def test_is_module_enabled_for_user_false_not_granted(self, app, db_session, test_user):
        """Тест когда модуль не выдан пользователю"""
        with app.app_context():
            module = create_test_module('not_granted', 'Not Granted')
            db_session.add(module)
            db_session.commit()

            result = ModuleService.is_module_enabled_for_user(test_user.id, 'not_granted')

            assert result is False

    def test_is_module_enabled_for_user_false_inactive(self, app, db_session, test_user):
        """Тест когда модуль неактивен"""
        with app.app_context():
            module = create_test_module('inactive_module', 'Inactive', is_active=False)
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=True)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.is_module_enabled_for_user(test_user.id, 'inactive_module')

            assert result is False

    def test_is_module_enabled_for_user_false_not_exists(self, app, db_session, test_user):
        """Тест когда модуль не существует"""
        with app.app_context():
            result = ModuleService.is_module_enabled_for_user(test_user.id, 'nonexistent_xyz')

            assert result is False


class TestGrantModuleToUser:
    """Тесты метода grant_module_to_user"""

    def test_grant_module_to_user_new(self, app, db_session, test_user):
        """Тест выдачи нового модуля пользователю"""
        with app.app_context():
            module = create_test_module('grant_new', 'Grant New')
            db_session.add(module)
            db_session.commit()

            user_module = ModuleService.grant_module_to_user(test_user.id, module.id)

            assert user_module is not None
            assert user_module.user_id == test_user.id
            assert user_module.module_id == module.id
            assert user_module.is_enabled is True
            assert user_module.granted_by_admin is False

    def test_grant_module_to_user_with_admin_flag(self, app, db_session, test_user):
        """Тест выдачи модуля админом"""
        with app.app_context():
            module = create_test_module('grant_admin', 'Grant Admin')
            db_session.add(module)
            db_session.commit()

            user_module = ModuleService.grant_module_to_user(test_user.id, module.id, granted_by_admin=True)

            assert user_module.granted_by_admin is True

    def test_grant_module_to_user_existing_disabled(self, app, db_session, test_user):
        """Тест выдачи уже существующего отключенного модуля"""
        with app.app_context():
            module = create_test_module('grant_existing', 'Grant Existing')
            db_session.add(module)
            db_session.commit()

            # Create disabled user module
            existing = UserModule(user_id=test_user.id, module_id=module.id,
                                is_enabled=False, granted_by_admin=False)
            db_session.add(existing)
            db_session.commit()
            existing_id = existing.id

            # Grant again
            user_module = ModuleService.grant_module_to_user(test_user.id, module.id)

            assert user_module.id == existing_id  # Same record
            assert user_module.is_enabled is True  # Now enabled

    def test_grant_module_preserves_admin_flag(self, app, db_session, test_user):
        """Тест что флаг granted_by_admin сохраняется"""
        with app.app_context():
            module = create_test_module('preserve_admin', 'Preserve')
            db_session.add(module)
            db_session.commit()

            # Grant by admin
            existing = UserModule(user_id=test_user.id, module_id=module.id,
                                is_enabled=False, granted_by_admin=True)
            db_session.add(existing)
            db_session.commit()

            # Grant again without admin flag
            user_module = ModuleService.grant_module_to_user(test_user.id, module.id, granted_by_admin=False)

            # Should preserve admin flag
            assert user_module.granted_by_admin is True


class TestRevokeModuleFromUser:
    """Тесты метода revoke_module_from_user"""

    def test_revoke_module_from_user_success(self, app, db_session, test_user):
        """Тест успешного отзыва модуля"""
        with app.app_context():
            module = create_test_module('revoke_test', 'Revoke')
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=True)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.revoke_module_from_user(test_user.id, module.id)

            assert result is True

            # Check module is disabled
            db_session.refresh(user_module)
            assert user_module.is_enabled is False

    def test_revoke_module_from_user_not_exists(self, app, db_session, test_user):
        """Тест отзыва несуществующего модуля"""
        with app.app_context():
            result = ModuleService.revoke_module_from_user(test_user.id, 999999)

            assert result is False


class TestToggleModuleForUser:
    """Тесты метода toggle_module_for_user"""

    def test_toggle_module_enabled_to_disabled(self, app, db_session, test_user):
        """Тест переключения включенного модуля в отключенный"""
        with app.app_context():
            module = create_test_module('toggle_test1', 'Toggle 1')
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=True)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.toggle_module_for_user(test_user.id, module.id)

            assert result is False  # Now disabled
            db_session.refresh(user_module)
            assert user_module.is_enabled is False

    def test_toggle_module_disabled_to_enabled(self, app, db_session, test_user):
        """Тест переключения отключенного модуля во включенный"""
        with app.app_context():
            module = create_test_module('toggle_test2', 'Toggle 2')
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id, is_enabled=False)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.toggle_module_for_user(test_user.id, module.id)

            assert result is True  # Now enabled
            db_session.refresh(user_module)
            assert user_module.is_enabled is True

    def test_toggle_module_not_exists_grants_it(self, app, db_session, test_user):
        """Тест что переключение несуществующего модуля выдает его"""
        with app.app_context():
            module = create_test_module('toggle_new', 'Toggle New')
            db_session.add(module)
            db_session.commit()

            result = ModuleService.toggle_module_for_user(test_user.id, module.id)

            assert result is True  # Granted and enabled

            # Verify it was created
            user_module = UserModule.query.filter_by(
                user_id=test_user.id, module_id=module.id
            ).first()
            assert user_module is not None
            assert user_module.is_enabled is True


class TestGrantDefaultModulesToUser:
    """Тесты метода grant_default_modules_to_user"""

    def test_grant_default_modules_to_user(self, app, db_session, test_user):
        """Тест выдачи всех дефолтных модулей"""
        with app.app_context():
            module1 = create_test_module('default_grant1', 'Default 1', is_default=True)
            module2 = create_test_module('default_grant2', 'Default 2',
                                        order=2, is_default=True)
            module3 = create_test_module('not_default_grant', 'Not Default',
                                        order=3, is_default=False)
            db_session.add_all([module1, module2, module3])
            db_session.commit()

            ModuleService.grant_default_modules_to_user(test_user.id)

            # Check that default modules were granted
            user_modules = UserModule.query.filter_by(user_id=test_user.id).all()
            module_ids = [um.module_id for um in user_modules]

            assert module1.id in module_ids
            assert module2.id in module_ids
            assert module3.id not in module_ids


class TestGrantModulesToUsers:
    """Тесты метода grant_modules_to_users"""

    def test_grant_modules_to_users_bulk(self, app, db_session, test_user):
        """Тест массовой выдачи модуля пользователям"""
        with app.app_context():
            # Create second user
            from app.auth.models import User
            user2 = User(username='testuser2', email='test2@example.com')
            user2.set_password('password')
            db_session.add(user2)
            db_session.commit()

            module = create_test_module('bulk_grant', 'Bulk Grant')
            db_session.add(module)
            db_session.commit()

            ModuleService.grant_modules_to_users(module.id, [test_user.id, user2.id], granted_by_admin=True)

            # Verify both users got the module
            user1_module = UserModule.query.filter_by(user_id=test_user.id, module_id=module.id).first()
            user2_module = UserModule.query.filter_by(user_id=user2.id, module_id=module.id).first()

            assert user1_module is not None
            assert user1_module.granted_by_admin is True
            assert user2_module is not None
            assert user2_module.granted_by_admin is True


class TestGetModuleStatistics:
    """Тесты метода get_module_statistics"""

    def test_get_module_statistics(self, app, db_session, test_user):
        """Тест получения статистики модулей"""
        with app.app_context():
            from app.auth.models import User
            user2 = User(username='statsuser', email='stats@example.com')
            user2.set_password('password')
            db_session.add(user2)
            db_session.commit()

            module = create_test_module('stats_module', 'Stats', is_default=True)
            db_session.add(module)
            db_session.commit()

            # Grant to both users, one by admin
            user_module1 = UserModule(user_id=test_user.id, module_id=module.id,
                                    is_enabled=True, granted_by_admin=True)
            user_module2 = UserModule(user_id=user2.id, module_id=module.id,
                                    is_enabled=False, granted_by_admin=False)
            db_session.add_all([user_module1, user_module2])
            db_session.commit()

            stats = ModuleService.get_module_statistics()

            assert 'stats_module' in stats
            module_stats = stats['stats_module']
            assert module_stats['total_users'] == 2
            assert module_stats['enabled_users'] == 1
            assert module_stats['granted_by_admin'] == 1
            assert module_stats['is_active'] is True
            assert module_stats['is_default'] is True


class TestCreateModule:
    """Тесты метода create_module"""

    def test_create_module_basic(self, app, db_session):
        """Тест создания базового модуля"""
        with app.app_context():
            module = ModuleService.create_module('create_test', 'Create Test',
                                                order=10, is_active=True)

            assert module is not None
            assert module.code == 'create_test'
            assert module.name == 'Create Test'
            assert module.order == 10
            assert module.is_active is True

    def test_create_module_with_kwargs(self, app, db_session):
        """Тест создания модуля с дополнительными параметрами"""
        with app.app_context():
            module = ModuleService.create_module(
                'kwargs_test', 'Kwargs Test',
                order=5,
                is_active=True,
                is_default=True,
                description='Test description'
            )

            assert module.is_default is True
            assert module.description == 'Test description'


class TestUpdateModule:
    """Тесты метода update_module"""

    def test_update_module_success(self, app, db_session):
        """Тест успешного обновления модуля"""
        with app.app_context():
            module = create_test_module('update_test', 'Old Name')
            db_session.add(module)
            db_session.commit()

            updated = ModuleService.update_module(module.id, name='New Name', order=5)

            assert updated is not None
            assert updated.name == 'New Name'
            assert updated.order == 5

    def test_update_module_not_exists(self, app, db_session):
        """Тест обновления несуществующего модуля"""
        with app.app_context():
            result = ModuleService.update_module(999999, name='Test')

            assert result is None

    def test_update_module_ignores_invalid_attributes(self, app, db_session):
        """Тест что игнорируются несуществующие атрибуты"""
        with app.app_context():
            module = create_test_module('invalid_attr', 'Test')
            db_session.add(module)
            db_session.commit()

            # Should not raise error
            updated = ModuleService.update_module(module.id,
                                                 name='Updated',
                                                 nonexistent_field='value')

            assert updated.name == 'Updated'


class TestDeleteModule:
    """Тесты метода delete_module"""

    def test_delete_module_success(self, app, db_session):
        """Тест успешного удаления модуля"""
        with app.app_context():
            module = create_test_module('delete_test', 'Delete')
            db_session.add(module)
            db_session.commit()
            module_id = module.id

            result = ModuleService.delete_module(module_id)

            assert result is True

            # Verify deleted
            deleted = SystemModule.query.get(module_id)
            assert deleted is None

    def test_delete_module_not_exists(self, app, db_session):
        """Тест удаления несуществующего модуля"""
        with app.app_context():
            result = ModuleService.delete_module(999999)

            assert result is False


class TestGetUserModuleSettings:
    """Тесты метода get_user_module_settings"""

    def test_get_user_module_settings_exists(self, app, db_session, test_user):
        """Тест получения существующих настроек"""
        with app.app_context():
            module = create_test_module('settings_test', 'Settings')
            db_session.add(module)
            db_session.commit()

            settings = {'theme': 'dark', 'notifications': True}
            user_module = UserModule(user_id=test_user.id, module_id=module.id,
                                   is_enabled=True, settings=settings)
            db_session.add(user_module)
            db_session.commit()

            result = ModuleService.get_user_module_settings(test_user.id, 'settings_test')

            assert result == settings

    def test_get_user_module_settings_not_exists(self, app, db_session, test_user):
        """Тест получения настроек несуществующего модуля"""
        with app.app_context():
            result = ModuleService.get_user_module_settings(test_user.id, 'nonexistent')

            assert result is None

    def test_get_user_module_settings_user_not_granted(self, app, db_session, test_user):
        """Тест получения настроек не выданного модуля"""
        with app.app_context():
            module = SystemModule(code='not_granted_settings', name='Not Granted',
                                order=1, is_active=True)
            db_session.add(module)
            db_session.commit()

            result = ModuleService.get_user_module_settings(test_user.id, 'not_granted_settings')

            assert result is None


class TestUpdateUserModuleSettings:
    """Тесты метода update_user_module_settings"""

    def test_update_user_module_settings_success(self, app, db_session, test_user):
        """Тест успешного обновления настроек"""
        with app.app_context():
            module = SystemModule(code='update_settings', name='Update Settings',
                                order=1, is_active=True)
            db_session.add(module)
            db_session.commit()

            user_module = UserModule(user_id=test_user.id, module_id=module.id,
                                   is_enabled=True, settings={})
            db_session.add(user_module)
            db_session.commit()

            new_settings = {'lang': 'ru', 'level': 5}
            result = ModuleService.update_user_module_settings(test_user.id, 'update_settings', new_settings)

            assert result is True

            db_session.refresh(user_module)
            assert user_module.settings == new_settings

    def test_update_user_module_settings_module_not_exists(self, app, db_session, test_user):
        """Тест обновления настроек несуществующего модуля"""
        with app.app_context():
            result = ModuleService.update_user_module_settings(test_user.id, 'nonexistent', {})

            assert result is False

    def test_update_user_module_settings_user_not_granted(self, app, db_session, test_user):
        """Тест обновления настроек не выданного модуля"""
        with app.app_context():
            module = SystemModule(code='not_granted_update', name='Not Granted',
                                order=1, is_active=True)
            db_session.add(module)
            db_session.commit()

            result = ModuleService.update_user_module_settings(test_user.id, 'not_granted_update', {})

            assert result is False
