"""Exercise the actual upgrade and downgrade without touching the app database."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

pytestmark = pytest.mark.smoke


def _migration(name: str):
    path = Path(__file__).parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_guest_ownership_and_downgrade_preserve_registered_results():
    engine = sa.create_engine("sqlite:///:memory:")
    previous = _migration("20261124_placement_tests.py")
    current = _migration("20261124_placement_personalization.py")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users VALUES (1)")
        with Operations.context(MigrationContext.configure(connection)):
            previous.upgrade()
            connection.exec_driver_sql("INSERT INTO placement_banks VALUES ('bank', 'fixture', '{}', 1, CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("INSERT INTO placement_attempts (id,user_id,bank_id,mode,status,state,result,created_at,updated_at) VALUES ('owned',1,'bank','quick','completed','{}','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            current.upgrade()
            connection.exec_driver_sql("INSERT INTO placement_guests VALUES ('guest', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            connection.exec_driver_sql("INSERT INTO placement_attempts (id,guest_key,bank_id,mode,status,state,created_at,updated_at) VALUES ('anonymous','guest','bank','quick','active','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            for user_id, guest_key in [(None, None), (1, 'guest')]:
                with pytest.raises(sa.exc.IntegrityError):
                    connection.exec_driver_sql("INSERT INTO placement_attempts (id,user_id,guest_key,bank_id,mode,status,state,created_at,updated_at) VALUES ('invalid',?,?,'bank','quick','completed','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (user_id, guest_key))
            current.downgrade()
        assert connection.exec_driver_sql("SELECT id,user_id FROM placement_attempts").all() == [("owned", 1)]
        assert not sa.inspect(connection).get_columns("placement_attempts")[1]["nullable"]
        assert "placement_guests" not in sa.inspect(connection).get_table_names()
    engine.dispose()
