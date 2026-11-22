#!/usr/bin/env python3
"""Install the reviewed pilot into the LOCAL database; default is a dry run.

Usage: .venv/bin/python scripts/install_plurals_pilot.py [--apply]
This script always connects over loopback; it cannot target a remote database.
"""

import argparse
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    values = dotenv_values(ROOT / ".env")
    from app import create_app
    from config.settings import Config
    from app.grammar_lab.content_pilot import install_plurals_pilot

    class Local(Config):
        SQLALCHEMY_DATABASE_URI = URL.create(
            "postgresql+psycopg2", username=values["POSTGRES_USER"], password=values["POSTGRES_PASSWORD"],
            host="127.0.0.1", port=int(values.get("POSTGRES_PORT", 5432)), database=values["POSTGRES_DB"])
        MAIL_SUPPRESS_SEND = True
        SCHEDULER_ENABLED = False

    app = create_app(config_class=Local)
    with app.app_context():
        report = install_plurals_pilot()
        if args.apply:
            from app.curriculum.models import Lessons
            from app.grammar_lab.models import GrammarTopic
            from app.utils.db import db

            topic = db.session.get(GrammarTopic, report["topic_id"])
            backup = {"topic_id": topic.id, "topic_content": topic.content,
                      "lessons": [{"id": key, "content": db.session.get(Lessons, key).content}
                                  for key in report["lesson_ids"]]}
            path = Path("/tmp") / ("llt-plurals-before-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
            path.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
            report = install_plurals_pilot(apply=True)
            report["backup"] = str(path)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
