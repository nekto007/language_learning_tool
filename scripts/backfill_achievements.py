"""Backfill achievements for all existing users.

Iterates every User row, ensures a UserStatistics record exists, then calls
check_all_achievements so every seeded achievement family is evaluated.
grant_achievement is idempotent (savepoint + IntegrityError catch), so this
is safe to run multiple times.

Flags:
    --dry-run    compute what would be granted without committing
    --verbose    print per-user summaries (default: print totals only)
    --no-db      skip DB, exit 0 (CI / import-only runs)

Usage:
    python scripts/backfill_achievements.py [--dry-run] [--verbose]
    flask backfill-achievements [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class UserResult:
    user_id: int
    username: str
    newly_granted: int
    codes: List[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    total_users: int = 0
    total_newly_granted: int = 0
    users_affected: int = 0
    results: List[UserResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core logic (separated from CLI / Flask glue so it's unit-testable)
# ---------------------------------------------------------------------------


def run_backfill(db_session, dry_run: bool = False, verbose: bool = False) -> BackfillReport:
    """Backfill achievements for all users.

    Caller is responsible for committing or rolling back the session.
    When dry_run=True this function skips the outer commit.  Note: sub-check
    functions inside check_all_achievements commit internally when they grant
    achievements, so in production dry_run does not prevent DB writes — it
    only skips the final aggregating commit.  In test environments the session
    is bound to an outer connection transaction that can be rolled back by the
    caller after this function returns.
    """
    from app.auth.models import User
    from app.achievements.services import AchievementService, StatisticsService

    report = BackfillReport()
    users = db_session.query(User).order_by(User.id).all()
    report.total_users = len(users)

    for user in users:
        try:
            stats = StatisticsService.get_or_create_statistics(user.id)
            db_session.flush()

            result = AchievementService.check_all_achievements(user.id)
            newly = result.get('all', [])
            if newly and not dry_run:
                db_session.commit()

            if newly:
                codes = [a.code for a in newly]
                report.users_affected += 1
                report.total_newly_granted += len(newly)
                ur = UserResult(
                    user_id=user.id,
                    username=user.username,
                    newly_granted=len(newly),
                    codes=codes,
                )
                report.results.append(ur)
                if verbose:
                    print(f"  user {user.id} ({user.username}): +{len(newly)} "
                          f"({', '.join(codes)})")
        except Exception as exc:
            report.errors.append(f"user_id={user.id}: {exc}")
            try:
                db_session.rollback()
            except Exception:
                pass

    return report


# ---------------------------------------------------------------------------
# CLI (standalone)
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backfill achievements for all users.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute grants without committing to DB")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-user grant details")
    parser.add_argument("--no-db", action="store_true",
                        help="Skip DB (CI / import-only check)")
    args = parser.parse_args(argv)

    if args.no_db:
        return 0

    sys.path.insert(0, str(PROJECT_ROOT))
    from app import create_app
    from app.utils.db import db

    app = create_app()
    with app.app_context():
        mode = "dry-run" if args.dry_run else "live"
        print(f"Achievement backfill starting ({mode}) ...")
        report = run_backfill(db.session, dry_run=args.dry_run, verbose=args.verbose)

        if args.dry_run:
            db.session.rollback()

        print(f"\nDone.")
        print(f"  Users processed : {report.total_users}")
        print(f"  Users affected  : {report.users_affected}")
        print(f"  Achievements    : {report.total_newly_granted}")
        if report.errors:
            print(f"\n  Errors ({len(report.errors)}):")
            for e in report.errors:
                print(f"    - {e}")

    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
