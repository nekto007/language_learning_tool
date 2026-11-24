"""Small, explicitly mapped follow-ups; a diagnostic error is only a signal."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.onboarding.placement_engine import LEVELS, PlacementError
from app.onboarding.placement_models import PlacementAttempt, PlacementReview
from app.utils.db import db
from app.utils.time_utils import study_day_date_for_tz


def _today(user_id: int) -> date:
    from app.auth.models import User

    return study_day_date_for_tz(db.session.get(User, user_id).timezone)


def _topic(slug: str) -> Any | None:
    from app.grammar_lab.models import GrammarTopic, GrammarExercise
    from app.grammar_lab.exercise_visibility import active_exercise_clause

    topic = GrammarTopic.query.filter_by(slug=slug).first()
    if topic is None or topic.level not in LEVELS:
        return None
    count = GrammarExercise.query.filter_by(topic_id=topic.id).filter(active_exercise_clause()).count()
    return topic if count >= 3 else None


def seed(attempt: PlacementAttempt) -> None:
    if not attempt.user_id or not attempt.applied_at:
        return
    due = attempt.result.get("effective_on")
    from datetime import date

    due_on = date.fromisoformat(due) if due else _today(attempt.user_id)
    for item in attempt.result.get("review_topics") or []:
        topic = _topic(item["slug"])
        if topic is None or LEVELS.index(topic.level) > LEVELS.index(attempt.result["recommended_level"]):
            continue
        if PlacementReview.query.filter_by(attempt_id=attempt.id, topic_slug=topic.slug).first() is None:
            db.session.add(
                PlacementReview(
                    user_id=attempt.user_id,
                    attempt_id=attempt.id,
                    topic_slug=topic.slug,
                    due_on=due_on,
                    state="candidate",
                    practice={},
                )
            )
    db.session.flush()


def due_review(user_id: int) -> PlacementReview | None:
    from flask import has_app_context

    if (
        not has_app_context()
        or type(user_id) is not int
        or not PlacementReview.query.filter_by(user_id=user_id).first()
    ):
        return None
    today = _today(user_id)
    if PlacementReview.query.filter_by(user_id=user_id, completed_on=today).first():
        return None
    attempts = (
        PlacementAttempt.query.filter_by(user_id=user_id, status="completed")
        .filter(PlacementAttempt.applied_at.isnot(None))
        .order_by(PlacementAttempt.applied_at.desc())
        .all()
    )
    applicable = next(
        (a for a in attempts if not a.result.get("effective_on") or a.result["effective_on"] <= today.isoformat()), None
    )
    if applicable is None:
        return None
    rows = (
        PlacementReview.query.filter_by(user_id=user_id, attempt_id=applicable.id)
        .filter(PlacementReview.state != "verified", PlacementReview.due_on <= today)
        .order_by(PlacementReview.due_on, PlacementReview.id)
        .all()
    )
    return next((r for r in rows if _topic(r.topic_slug) is not None), None)


def item_for(row: PlacementReview, section: str = "optional") -> Any | None:
    from app.daily_plan.items import PlanItem

    topic = _topic(row.topic_slug)
    if topic is None:
        return None
    return PlanItem(
        id=f"grammar_review:placement:{row.id}:topic:{topic.id}",
        kind="grammar_review",
        section=section,
        title=("Проверим тему: " if row.state == "candidate" else "Закрепим: ") + (topic.title_ru or topic.title),
        subtitle="По результату теста · 3 задания",
        eta_minutes=3,
        completed=False,
        completion_signal="grammar_exercises",
        url=f"/placement/review/{row.id}",
        data={
            "placement_review_id": row.id,
            "topic_id": topic.id,
            "topic_slug": topic.slug,
            "topic_level": topic.level,
        },
    )


def plan_item(user_id: int, section: str = "optional") -> Any | None:
    row = due_review(user_id)
    return item_for(row, section) if row else None


def replace_slot(user_id: int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve the first course lesson, SRS and finals; never grow today's load."""
    candidate = plan_item(user_id, "required")
    if candidate is None or any((i.get("data") or {}).get("placement_review_id") for i in items):
        return items
    choices = [
        index
        for index, item in enumerate(items)
        if (item.get("data") or {}).get("minimum_filler")
        or (index > 0 and item.get("kind") == "curriculum" and item.get("lesson_type") != "final_test")
    ]
    if not choices:
        return items
    changed = list(items)
    index = choices[-1]
    if int(changed[index].get("eta_minutes") or 0) < candidate.eta_minutes:
        return items
    changed[index] = candidate.to_dict()
    return changed


def owned_review(user_id: int, key: str) -> PlacementReview:
    row = PlacementReview.query.filter_by(user_id=user_id, id=key).first()
    if row is None:
        raise PlacementError("not_found", 404)
    return row


def from_item(user_id: int, item_id: str) -> PlacementReview:
    pieces = item_id.split(":")
    if len(pieces) != 5 or pieces[:2] != ["grammar_review", "placement"] or pieces[3] != "topic":
        raise PlacementError("invalid_input")
    # Format is grammar_review:placement:<UUID>:topic:<topic-id>.
    return owned_review(user_id, pieces[2])


def complete(user_id: int, key: str, correct: int, total: int) -> None:
    row = owned_review(user_id, key)
    if total != 3 or not 0 <= correct <= total:
        raise PlacementError("invalid_input")
    row.completed_on = _today(user_id)
    row.state = "verified" if correct == total else "practice"
    row.due_on = row.completed_on + timedelta(days=2)
    row.practice = {"first_correct": correct, "total": total}
    db.session.flush()


def unreachable(user_id: int, key: str) -> bool:
    row = PlacementReview.query.filter_by(user_id=user_id, id=key).first()
    return (
        row is None
        or _topic(row.topic_slug) is None
        or (row.completed_on != _today(user_id) and (row.state == "verified" or row.due_on > _today(user_id)))
    )


def pace_adjusted(user_id: int) -> bool:
    from app.daily_plan.models import DailyPlanLog

    today = _today(user_id)
    rows = DailyPlanLog.query.filter(
        DailyPlanLog.user_id == user_id, DailyPlanLog.plan_date >= today - timedelta(days=7)
    ).all()
    return any(
        any((i.get("data") or {}).get("placement_review_id") for i in (r.plan_json or {}).get("items", []))
        for r in rows
    )
