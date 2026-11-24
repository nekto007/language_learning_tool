from flask import Blueprint
from flask.blueprints import BlueprintSetupState

onboarding_bp = Blueprint('onboarding', __name__)

from . import placement_models  # noqa: F401
from . import routes  # noqa: E402, F401
from . import placement_routes  # noqa: E402, F401

from .placement_bank import install_bank

@onboarding_bp.record_once
def register_placement_cli(state: BlueprintSetupState) -> None:
    state.app.cli.add_command(install_bank)
    from flask_login import user_logged_in
    from .placement_guests import claim_after_login, cleanup_command
    state.app.cli.add_command(cleanup_command)
    user_logged_in.connect(claim_after_login, sender=state.app, weak=False)
