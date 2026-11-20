"""Apply reviewed Grammar Lab prompt constraints without reimporting exercises."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.grammar_lab.prompt_manifest import parse_json, validate_manifest
from app.utils.db import db


@dataclass
class PromptReport:
    applied: bool = False
    updates: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def as_dict(self):
        return deepcopy(self.__dict__)


def load_manifest(path):
    document = parse_json(Path(path).read_bytes())
    validate_manifest(document)
    return document


def _source_content(content):
    if not isinstance(content, dict) or content.get("source") != "json_import":
        return None
    return {key: value for key, value in content.items() if key != "source"}


def _identity(change):
    return {
        "level": change["level"],
        "topic_slug": f"{change['level'].lower()}-{change['module_order']}",
        "source_session": change["session_number"],
        "source_order": change["exercise_order"],
        "exercise_type": change["exercise_type"],
    }


def patch_prompts(session, manifest, *, apply=False):
    """Match exact full before/after content, preflight everything, then commit.

    The old importer did not save session numbers. Session/order/title alone can
    never identify a target: identical content is a conflict, including duplicate
    rows with the same primary answer. All topic/exercise IDs, order, attempts,
    SRS state and answer keys stay in place. One reviewed alternatives exception
    broadens accepted answers, enforced in the shared manifest validator.
    """
    sources, changes = validate_manifest(manifest)
    if session.new or session.dirty or session.deleted:
        raise ValueError("Refusing unrelated pending database changes")
    report, plan, seen_ids = PromptReport(), [], set()
    try:
        with session.no_autoflush:
            topics_by_source = {}
            # A stable lock order serializes this rollout with another rollout.
            # No content is written until all eighty targets have been checked.
            for source in sorted(sources, key=lambda item: item["path"]):
                slug = f"{source['level'].lower()}-{source['module_order']}"
                query = select(GrammarTopic).where(GrammarTopic.slug == slug).execution_options(populate_existing=True)
                if apply:
                    query = query.with_for_update()
                topics = session.execute(query).scalars().all()
                if len(topics) != 1 or topics[0].level != source["level"]:
                    report.unavailable.append(
                        {"topic_slug": slug, "reason": "Exact conventional topic slug/level absent"}
                    )
                    topics_by_source[source["path"]] = None
                    continue
                topic = topics[0]
                query = (
                    select(GrammarExercise)
                    .where(GrammarExercise.topic_id == topic.id)
                    .order_by(GrammarExercise.id)
                    .execution_options(populate_existing=True)
                )
                if apply:
                    query = query.with_for_update()
                rows = session.execute(query).scalars().all()
                topics_by_source[source["path"]] = (topic, rows)
            for change in changes:
                target = topics_by_source[change["source"]]
                if target is None:
                    continue
                topic, rows = target
                detail = _identity(change)
                matches = [
                    row
                    for row in rows
                    if row.exercise_type == change["exercise_type"]
                    and _source_content(row.content) in (change["content_before"], change["content_after"])
                ]
                if len(matches) != 1:
                    status = report.unavailable if not matches else report.conflicts
                    status.append(
                        {
                            **detail,
                            "reason": "Exact imported before/after content absent"
                            if not matches
                            else "Multiple exact imported content matches",
                        }
                    )
                    continue
                row = matches[0]
                if (
                    row.id in seen_ids
                    or row.order != change["exercise_order"]
                    or row.difficulty != max(1, min(3, int(change.get("difficulty") or 1)))
                ):
                    report.conflicts.append(
                        {**detail, "id": row.id, "reason": "Ambiguous reuse or source order/difficulty mismatch"}
                    )
                    continue
                seen_ids.add(row.id)
                detail["id"] = row.id
                before = deepcopy(row.content)
                if _source_content(before) == change["content_after"]:
                    report.unchanged.append(detail)
                else:
                    after = {**deepcopy(change["content_after"]), "source": "json_import"}
                    report.updates.append(detail)
                    plan.append((row, before, after, (row.topic_id, row.exercise_type, row.order, row.difficulty)))
        if not apply:
            return report
        if report.unavailable or report.conflicts:
            raise ValueError(
                f"Grammar prompt apply refused: {len(report.unavailable)} unavailable, {len(report.conflicts)} conflicts; run dry-run for exact targets"
            )
        # Locks were acquired before matching. Refresh once more so a cached ORM
        # identity or a callback cannot turn a dry-run snapshot into a blind write.
        for row, before, _, metadata in plan:
            current = session.execute(
                select(GrammarExercise)
                .where(GrammarExercise.id == row.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if (
                current is None
                or current.content != before
                or (current.topic_id, current.exercise_type, current.order, current.difficulty) != metadata
            ):
                raise ValueError(f"Exercise changed after preflight: {row.id}")
        for row, _, after, _ in plan:
            row.content = deepcopy(after)
        session.commit()
        session.expire_all()
    except Exception:
        if apply:
            session.rollback()
        raise
    report.applied = True
    return report


@click.command("grammar-prompts")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--apply", "apply_changes", is_flag=True, help="Apply the fully checked pack in one transaction")
@click.option("--report", "report_path", type=click.Path(dir_okay=False, path_type=Path))
@with_appcontext
def grammar_prompts_command(manifest, apply_changes, report_path):
    """Patch reviewed imported prompts in place; default is a read-only dry-run."""
    try:
        report = patch_prompts(db.session, load_manifest(manifest), apply=apply_changes)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise click.ClickException(str(error)) from error
    if report_path:
        report_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    click.echo(
        f"{'APPLIED' if report.applied else 'DRY RUN'}: {len(report.updates)} updates, {len(report.unchanged)} unchanged, {len(report.unavailable)} unavailable, {len(report.conflicts)} conflicts"
    )
    for status in ("unavailable", "conflicts"):
        for detail in getattr(report, status):
            click.echo(f"{status}: {json.dumps(detail, ensure_ascii=False)}")
    if not report.applied:
        click.echo("No database changes. Missing, ambiguous or drifted targets block the entire apply.")
