"""
Tests for modules migrations
Тесты миграций модулей
"""
import pytest
from unittest.mock import patch, MagicMock
from app.modules.migrations import (
    create_module_tables,
    seed_initial_modules,
    migrate_existing_users,
    run_migration
)
from app.modules.models import SystemModule, UserModule


class TestCreateModuleTables:
    """Тесты функции create_module_tables"""

    @patch('app.modules.migrations.db.create_all')
    def test_create_module_tables_calls_create_all(self, mock_create_all):
        """Тест что вызывается db.create_all()"""
        create_module_tables()

        mock_create_all.assert_called_once()


class TestSeedInitialModules:
    """Тесты функции seed_initial_modules"""

    def test_seed_initial_modules_creates_modules(self, app, db_session):
        """Тест создания начальных модулей"""
        with app.app_context():
            # Убеждаемся что модулей нет
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            # Проверяем что модули созданы
            modules = SystemModule.query.all()
            assert len(modules) == 5  # curriculum, words, books, study, reminders

    def test_seed_initial_modules_creates_curriculum(self, app, db_session):
        """Тест создания модуля curriculum"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            curriculum = SystemModule.query.filter_by(code='curriculum').first()
            assert curriculum is not None
            assert curriculum.name == 'Учебная программа'
            assert curriculum.blueprint_name == 'curriculum'
            assert curriculum.is_active == True

    def test_seed_initial_modules_creates_words(self, app, db_session):
        """Тест создания модуля words"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            words = SystemModule.query.filter_by(code='words').first()
            assert words is not None
            assert words.is_default == True  # Should be default

    def test_seed_initial_modules_creates_books(self, app, db_session):
        """Тест создания модуля books"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            books = SystemModule.query.filter_by(code='books').first()
            assert books is not None
            assert books.is_default == False  # Not default

    def test_seed_initial_modules_creates_study(self, app, db_session):
        """Тест создания модуля study"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            study = SystemModule.query.filter_by(code='study').first()
            assert study is not None
            assert study.is_default == True

    def test_seed_initial_modules_creates_reminders(self, app, db_session):
        """Тест создания модуля reminders"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            reminders = SystemModule.query.filter_by(code='reminders').first()
            assert reminders is not None

    def test_seed_initial_modules_skips_if_exists(self, app, db_session):
        """Тест что не создает модули если они уже есть"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            # Создаем один модуль
            module = SystemModule(
                code='test',
                name='Test',
                description='Test module',
                is_active=True,
                order=1
            )
            db_session.add(module)
            db_session.commit()

            initial_count = SystemModule.query.count()

            # Вызываем seed - не должно добавить новые модули
            seed_initial_modules()

            final_count = SystemModule.query.count()
            assert final_count == initial_count

    def test_seed_initial_modules_all_have_required_fields(self, app, db_session):
        """Тест что все модули имеют обязательные поля"""
        with app.app_context():
            SystemModule.query.delete()
            db_session.commit()

            seed_initial_modules()

            modules = SystemModule.query.all()
            for module in modules:
                assert module.code is not None
                assert module.name is not None
                assert module.is_active is not None
                assert module.order is not None


class TestMigrateExistingUsers:
    """Тесты функции migrate_existing_users"""

    def test_migrate_existing_users_gives_default_modules(self, app, db_session, test_user):
        """Тест выдачи дефолтных модулей пользователям"""
        with app.app_context():
            # Создаем дефолтный модуль
            module = SystemModule(
                code='default_test',
                name='Default Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1
            )
            db_session.add(module)
            db_session.commit()

            # Удаляем существующие связи
            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            # Проверяем что пользователь получил модуль
            user_modules = UserModule.query.filter_by(user_id=test_user.id).all()
            assert len(user_modules) > 0

    def test_migrate_existing_users_skips_users_with_modules(self, app, db_session, test_user):
        """Тест что не дает модули пользователям, у которых они уже есть"""
        with app.app_context():
            # Создаем дефолтный модуль
            module = SystemModule(
                code='default_test_skip',
                name='Default Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1,
                blueprint_name='test_skip',
                url_prefix='/test_skip'
            )
            db_session.add(module)
            db_session.commit()

            # Даем пользователю какой-то модуль
            user_module = UserModule(
                user_id=test_user.id,
                module_id=module.id,
                is_enabled=True
            )
            db_session.add(user_module)
            db_session.commit()

            initial_count = UserModule.query.filter_by(user_id=test_user.id).count()

            migrate_existing_users()

            final_count = UserModule.query.filter_by(user_id=test_user.id).count()
            # Не должно добавиться новых модулей
            assert final_count == initial_count

    def test_migrate_existing_users_only_default_modules(self, app, db_session, test_user):
        """Тест что выдаются только дефолтные модули"""
        with app.app_context():
            # Создаем дефолтный и не-дефолтный модуль
            default_module = SystemModule(
                code='default',
                name='Default',
                description='Test',
                is_active=True,
                is_default=True,
                order=1
            )
            non_default_module = SystemModule(
                code='non_default',
                name='Non Default',
                description='Test',
                is_active=True,
                is_default=False,
                order=2
            )
            db_session.add(default_module)
            db_session.add(non_default_module)
            db_session.commit()

            # Удаляем существующие связи
            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            # Проверяем что пользователь получил только дефолтный модуль
            user_modules = UserModule.query.filter_by(user_id=test_user.id).all()
            module_ids = [um.module_id for um in user_modules]

            assert default_module.id in module_ids
            assert non_default_module.id not in module_ids

    def test_migrate_existing_users_sets_enabled_true(self, app, db_session, test_user):
        """Тест что модули выдаются включенными"""
        with app.app_context():
            module = SystemModule(
                code='test',
                name='Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1
            )
            db_session.add(module)
            db_session.commit()

            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            user_module = UserModule.query.filter_by(user_id=test_user.id).first()
            assert user_module.is_enabled == True

    def test_migrate_existing_users_sets_granted_by_admin_false(self, app, db_session, test_user):
        """Тест что granted_by_admin устанавливается в False"""
        with app.app_context():
            module = SystemModule(
                code='test_granted',
                name='Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1,
                blueprint_name='test_granted',
                url_prefix='/test_granted'
            )
            db_session.add(module)
            db_session.commit()

            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            user_module = UserModule.query.filter_by(user_id=test_user.id).first()
            assert user_module.granted_by_admin == False


class TestRunMigration:
    """Тесты функции run_migration"""

    @patch('app.modules.migrations.migrate_existing_users')
    @patch('app.modules.migrations.seed_initial_modules')
    @patch('app.modules.migrations.create_module_tables')
    def test_run_migration_calls_all_functions(self, mock_create, mock_seed, mock_migrate):
        """Тест что вызываются все функции миграции"""
        run_migration()

        mock_create.assert_called_once()
        mock_seed.assert_called_once()
        mock_migrate.assert_called_once()

    @patch('app.modules.migrations.migrate_existing_users')
    @patch('app.modules.migrations.seed_initial_modules')
    @patch('app.modules.migrations.create_module_tables')
    def test_run_migration_calls_in_correct_order(self, mock_create, mock_seed, mock_migrate):
        """Тест что функции вызываются в правильном порядке"""
        call_order = []

        mock_create.side_effect = lambda: call_order.append('create')
        mock_seed.side_effect = lambda: call_order.append('seed')
        mock_migrate.side_effect = lambda: call_order.append('migrate')

        run_migration()

        assert call_order == ['create', 'seed', 'migrate']
