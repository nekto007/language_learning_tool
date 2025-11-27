"""
Tests for modules migrations
Тесты миграций модулей - OPTIMIZED VERSION with subtransactions
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

# Mark to skip autouse fixtures that interfere with module tests
pytestmark = pytest.mark.usefixtures('_skip_autouse_module_fixtures')


@pytest.fixture(autouse=True, scope='function')
def clean_modules(db_session):
    """
    Clean modules before and after each test.
    Uses DELETE which is faster than drop_all/create_all.
    """
    # Clean before test to ensure fresh state
    try:
        UserModule.query.delete()
        SystemModule.query.delete()
        db_session.commit()
    except Exception:
        db_session.rollback()

    yield

    # Clean after test for next test
    try:
        UserModule.query.delete()
        SystemModule.query.delete()
        db_session.commit()
    except Exception:
        db_session.rollback()


class TestCreateModuleTables:
    """Тесты функции create_module_tables"""

    @patch('app.modules.migrations.db.create_all')
    def test_create_module_tables_calls_create_all(self, mock_create_all):
        """Тест что вызывается db.create_all()"""
        create_module_tables()
        mock_create_all.assert_called_once()


class TestSeedInitialModulesBasic:
    """Тесты функции seed_initial_modules - basic functionality"""

    def test_seed_initial_modules_creates_5_modules(self, app, db_session):
        """Тест создания 5 модулей за один раз"""
        with app.app_context():
            seed_initial_modules()

            # Check all modules in one query
            modules = SystemModule.query.all()
            assert len(modules) == 5

            # Get all codes
            codes = {m.code for m in modules}
            expected = {'curriculum', 'words', 'books', 'study', 'reminders'}
            assert codes == expected

            # Check all have required fields
            for module in modules:
                assert module.code is not None
                assert module.name is not None
                assert module.is_active is not None
                assert module.order is not None

    def test_seed_initial_modules_curriculum_details(self, app, db_session):
        """Тест деталей модуля curriculum"""
        with app.app_context():
            seed_initial_modules()

            curriculum = SystemModule.query.filter_by(code='curriculum').first()
            assert curriculum is not None
            assert curriculum.name == 'Учебная программа'
            assert curriculum.blueprint_name == 'curriculum'
            assert curriculum.is_active == True

    def test_seed_initial_modules_default_modules(self, app, db_session):
        """Тест что words и study дефолтные"""
        with app.app_context():
            seed_initial_modules()

            words = SystemModule.query.filter_by(code='words').first()
            study = SystemModule.query.filter_by(code='study').first()
            books = SystemModule.query.filter_by(code='books').first()

            assert words.is_default == True
            assert study.is_default == True
            assert books.is_default == False

    def test_seed_initial_modules_skips_if_exists(self, app, db_session):
        """Тест что не создает модули если они уже есть"""
        with app.app_context():
            # Создаем один модуль
            module = SystemModule(
                code='test_unique',
                name='Test',
                description='Test module',
                is_active=True,
                order=1
            )
            db_session.add(module)
            db_session.commit()

            initial_count = SystemModule.query.count()
            seed_initial_modules()
            final_count = SystemModule.query.count()

            assert final_count == initial_count


class TestMigrateExistingUsers:
    """Тесты функции migrate_existing_users"""

    def test_migrate_existing_users_gives_default_modules(self, app, db_session, test_user):
        """Тест выдачи дефолтных модулей пользователям"""
        with app.app_context():
            module = SystemModule(
                code='default_test_unique',
                name='Default Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1
            )
            db_session.add(module)
            db_session.commit()

            migrate_existing_users()

            user_modules = UserModule.query.filter_by(user_id=test_user.id).all()
            assert len(user_modules) > 0

    def test_migrate_existing_users_skips_users_with_modules(self, app, db_session, test_user):
        """Тест что не дает модули пользователям, у которых они уже есть"""
        with app.app_context():
            module = SystemModule(
                code='skip_test_unique',
                name='Default Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1,
                blueprint_name='skip_test',
                url_prefix='/skip_test'
            )
            db_session.add(module)
            db_session.commit()

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

            assert final_count == initial_count

    def test_migrate_existing_users_only_default_modules(self, app, db_session, test_user):
        """Тест что выдаются только дефолтные модули"""
        with app.app_context():
            default_module = SystemModule(
                code='default_unique',
                name='Default',
                description='Test',
                is_active=True,
                is_default=True,
                order=1
            )
            non_default_module = SystemModule(
                code='non_default_unique',
                name='Non Default',
                description='Test',
                is_active=True,
                is_default=False,
                order=2
            )
            db_session.add(default_module)
            db_session.add(non_default_module)
            db_session.commit()

            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            user_modules = UserModule.query.filter_by(user_id=test_user.id).all()
            module_ids = [um.module_id for um in user_modules]

            assert default_module.id in module_ids
            assert non_default_module.id not in module_ids

    def test_migrate_existing_users_module_properties(self, app, db_session, test_user):
        """Тест что модули имеют правильные свойства (enabled=True, granted_by_admin=False)"""
        with app.app_context():
            module = SystemModule(
                code='props_test_unique',
                name='Test',
                description='Test',
                is_active=True,
                is_default=True,
                order=1,
                blueprint_name='props_test',
                url_prefix='/props_test'
            )
            db_session.add(module)
            db_session.commit()

            UserModule.query.filter_by(user_id=test_user.id).delete()
            db_session.commit()

            migrate_existing_users()

            user_module = UserModule.query.filter_by(user_id=test_user.id).first()
            assert user_module.is_enabled == True
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
