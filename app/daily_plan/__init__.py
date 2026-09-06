from app.daily_plan.models import (
    Mission,
    MissionPhase,
    MissionPlan,
    MissionType,
    PhaseKind,
    PrimaryGoal,
    PrimarySource,
    SourceKind,
)

__all__ = [
    "MissionType",
    "PhaseKind",
    "SourceKind",
    "MissionPhase",
    "Mission",
    "PrimaryGoal",
    "PrimarySource",
    "MissionPlan",
]

# Register the route-progress model with the metadata: its only importers are
# lazy (inside view functions), so a fresh create_all() otherwise never sees the
# user_route_progress table.
from app.daily_plan import route_progress as _route_progress  # noqa: E402,F401
