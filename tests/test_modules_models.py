"""
Tests for modules models
Тесты моделей модулей
"""
import pytest
from app.modules.models import SystemModule, UserModule


class TestSystemModuleModel:
    """Тесты модели SystemModule"""

    def test_create_system_module(self, app, db_session):
        """Тест создания системного модуля"""
        with app.app_context():
            module = SystemModule(
                code='test_module',
                name='Test Module',
                description='Test description',
                icon='book',
                is_active=True,
                is_default=False,
                order=1,
                blueprint_name='test',
                url_prefix='/test'
            )
            db_session.add(module)
            db_session.commit()

            assert module.id is not None
            assert module.code == 'test_module'
            assert module.name == 'Test Module'

    def test_system_module_repr(self, app, db_session):
        """Тест __repr__ метода"""
        with app.app_context():
            import uuid
            unique_code = f'curriculum_{uuid.uuid4().hex[:8]}'

            module = SystemModule(
                code=unique_code,
                name='Curriculum Module'
            )
            db_session.add(module)
            db_session.commit()

            repr_str = repr(module)
            assert 'SystemModule' in repr_str
            assert unique_code in repr_str
            assert 'Curriculum Module' in repr_str

    def test_system_module_to_dict(self, app, db_session):
        """Тест метода to_dict"""
        with app.app_context():
            import uuid
            unique_code = f'books_{uuid.uuid4().hex[:8]}'

            module = SystemModule(
                code=unique_code,
                name='Books Module',
                description='Manage books',
                icon='book-open',
                is_active=True,
                is_default=True,
                order=2,
                blueprint_name='books',
                url_prefix='/books'
            )
            db_session.add(module)
            db_session.commit()

            module_dict = module.to_dict()
            assert module_dict['id'] == module.id
            assert module_dict['code'] == unique_code
            assert module_dict['name'] == 'Books Module'
            assert module_dict['description'] == 'Manage books'
            assert module_dict['icon'] == 'book-open'
            assert module_dict['is_active'] is True
            assert module_dict['is_default'] is True
            assert module_dict['order'] == 2
            assert module_dict['blueprint_name'] == 'books'
            assert module_dict['url_prefix'] == '/books'
            assert 'created_at' in module_dict
            assert 'updated_at' in module_dict


class TestUserModuleModel:
    """Тесты модели UserModule"""

    def test_create_user_module(self, app, db_session, test_user):
        """Тест создания связи пользователь-модуль"""
        with app.app_context():
            # Создаем системный модуль
            system_module = SystemModule(
                code='test',
                name='Test'
            )
            db_session.add(system_module)
            db_session.flush()

            # Создаем связь
            user_module = UserModule(
                user_id=test_user.id,
                module_id=system_module.id,
                is_enabled=True,
                granted_by_admin=False,
                settings={'theme': 'dark'}
            )
            db_session.add(user_module)
            db_session.commit()

            assert user_module.id is not None
            assert user_module.user_id == test_user.id
            assert user_module.module_id == system_module.id
            assert user_module.is_enabled is True
            assert user_module.settings == {'theme': 'dark'}

    def test_user_module_repr(self, app, db_session, test_user):
        """Тест __repr__ метода"""
        with app.app_context():
            import uuid
            unique_code = f'words_{uuid.uuid4().hex[:8]}'

            system_module = SystemModule(code=unique_code, name='Words')
            db_session.add(system_module)
            db_session.flush()

            user_module = UserModule(
                user_id=test_user.id,
                module_id=system_module.id
            )
            db_session.add(user_module)
            db_session.commit()

            repr_str = repr(user_module)
            assert 'UserModule' in repr_str
            assert str(test_user.id) in repr_str
            assert str(system_module.id) in repr_str

    def test_user_module_to_dict(self, app, db_session, test_user):
        """Тест метода to_dict"""
        with app.app_context():
            import uuid
            unique_code = f'curriculum_{uuid.uuid4().hex[:8]}'

            system_module = SystemModule(
                code=unique_code,
                name='Curriculum Module'
            )
            db_session.add(system_module)
            db_session.flush()

            user_module = UserModule(
                user_id=test_user.id,
                module_id=system_module.id,
                is_enabled=True,
                granted_by_admin=True,
                settings={'level': 'A1'}
            )
            db_session.add(user_module)
            db_session.commit()

            module_dict = user_module.to_dict()
            assert module_dict['id'] == user_module.id
            assert module_dict['user_id'] == test_user.id
            assert module_dict['module_id'] == system_module.id
            assert module_dict['module_code'] == unique_code
            assert module_dict['module_name'] == 'Curriculum Module'
            assert module_dict['is_enabled'] is True
            assert module_dict['granted_by_admin'] is True
            assert module_dict['settings'] == {'level': 'A1'}
            assert 'granted_at' in module_dict
            assert 'created_at' in module_dict
            assert 'updated_at' in module_dict
