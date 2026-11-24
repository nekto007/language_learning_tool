"""Synthetic contract bank only; production diagnostic material is private."""

from app.onboarding.placement_bank import LEVELS, SKILLS, MIN_ITEMS


def synthetic_bank() -> dict:
    items = []
    for level in LEVELS:
        for skill in SKILLS:
            for index in range(MIN_ITEMS[skill]):
                row = {
                    "id": f"{level}-{skill}-{index}",
                    "level": level,
                    "skill": skill,
                    "input": "text" if skill == "writing" else "choice",
                    "prompt": f"Synthetic {skill} item",
                    "answers": ["A correct answer"],
                    "topic": f"Synthetic {skill} topic",
                }
                if skill != "writing":
                    row["options"] = ["A correct answer", "Wrong answer", "Another answer"]
                if skill == "reading":
                    row["passage"] = "An artificial passage used only by tests."
                if skill == "listening":
                    row["audio_url"] = "/static/audio/synthetic.mp3"
                items.append(row)
    return {"schema_version": 1, "label": "Synthetic test bank", "items": items}
