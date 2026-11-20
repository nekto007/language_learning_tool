"""Small, authored learning goals and starter examples for native lessons.

Only explicitly public teaching material is projected. Builder fields, answer
keys and arbitrary content metadata never become part of this payload.
"""

import json


def _text(value, limit=320):
    from app.api.native_lessons import plain

    if not isinstance(value, str) or len(value) > 5000:
        return ""
    value = plain(value).strip()
    return value if len(value) <= limit else ""


def learning_guidance(lesson):
    content = lesson.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return {}
    if not isinstance(content, dict):
        return {}
    starter = content.get("starter")
    starter = starter if isinstance(starter, dict) else {}
    result = {}
    goal = _text(content.get("learning_goal")) or _text(starter.get("goal"))
    if goal:
        result["learning_goal"] = goal
    rows = starter.get("lines")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        return result
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            return result
        english, russian = _text(row.get("english")), _text(row.get("russian"))
        if not english or not russian:
            return result
        lines.append({"english": english, "russian": russian})
    result["introduction"] = {
        "title": _text(starter.get("title"), 160) or "Попробуй перед карточками",
        "lines": lines,
    }
    return result
