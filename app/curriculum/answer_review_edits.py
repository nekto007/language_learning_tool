"""Handle authored answer lists shared by the course and Grammar Lab editors."""
from app.utils.normalization import normalize_quiz_answer

ALIAS_FIELDS = ('alternatives', 'alternative_answers', 'acceptable_answers')


def answer_aliases(row: dict) -> list[str]:
    return list(dict.fromkeys(answer for key in ALIAS_FIELDS if isinstance(row.get(key), list)
                              for answer in row[key] if isinstance(answer, str)))


def replace_text_key(row: dict, key: str, answer: str) -> dict:
    """Drop alias copies of the retired key and of the promoted answer."""
    keys = {normalize_quiz_answer(row[key]), normalize_quiz_answer(answer)}
    patch = {key: answer}
    for field in ALIAS_FIELDS:
        aliases = row.get(field)
        if isinstance(aliases, list):
            retained = [a for a in aliases if not isinstance(a, str) or normalize_quiz_answer(a) not in keys]
            if retained != aliases:
                patch[field] = retained
    return patch
