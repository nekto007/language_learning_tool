import logging
import warnings

logger = logging.getLogger(__name__)


def _legacy_init_db(app):
    """
    DEPRECATED: Legacy database initialization function.

    Schema management is done exclusively through Alembic migrations:
        flask db upgrade head

    Seed data is managed via CLI:
        flask seed

    This function exists only for backward compatibility and will be removed
    in a future release.
    """
    warnings.warn(
        "_legacy_init_db is deprecated. Use 'flask db upgrade' for schema "
        "and 'flask seed' for seed data.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.info("_legacy_init_db called (deprecated, no-op)")


def init_db(app=None):
    """
    DEPRECATED: Wrapper kept for backward compatibility.
    Delegates to _legacy_init_db which is a no-op with a deprecation warning.
    """
    if app is None:
        from flask import current_app
        app = current_app._get_current_object()
    _legacy_init_db(app)
