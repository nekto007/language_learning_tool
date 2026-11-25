"""Publication of the two site-only rehearsal scenes."""

import json

from app.admin.site_settings import SiteSettings, set_site_setting
from app.public_copy import StalePublication, digest
from app.utils.db import db
from app.utils.normalization import normalize_quiz_answer

_KEY = 'rehearsal.clothing'
ROUNDS = ('jacket', 'shoes')
TEXT_FIELDS = frozenset(('title', 'task', 'opening', 'hint', 'clarification', 'offer',
                         'color_reply', 'other_color_reply', 'accept_label', 'accept_reply', 'try_reply',
                         'decline_label', 'decline_reply'))


def validate_rehearsal(raw: str) -> dict:
    """Validate the whole document before either scene can be published."""
    if len(raw) > 20_000:
        raise ValueError('Документ должен содержать до 20 000 символов.')
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ValueError('Проверьте формат JSON.') from error
    if not isinstance(document, dict) or document.keys() != set(ROUNDS):
        raise ValueError('Добавьте сцены jacket и shoes.')
    for key, scene in document.items():
        if not isinstance(scene, dict) or scene.keys() != TEXT_FIELDS | {'accepted'}:
            raise ValueError(f'Проверьте состав полей сцены «{key}».')
        for field in TEXT_FIELDS:
            value = scene[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise ValueError(f'Заполните поле «{field}» в сцене «{key}» текстом до 500 символов.')
            scene[field] = value.strip()
        answers = scene['accepted']
        if (not isinstance(answers, list) or not 2 <= len(answers) <= 30
                or any(not isinstance(answer, str) or len(answer) > 240 or not normalize_quiz_answer(answer)
                       for answer in answers)
                or len({normalize_quiz_answer(answer) for answer in answers}) != len(answers)):
            raise ValueError(f'Укажите от 2 до 30 разных реплик в сцене «{key}».')
        if scene['accept_label'] == scene['decline_label']:
            raise ValueError(f'Задайте две разные развилки в сцене «{key}».')
        scene['accepted'] = [answer.strip() for answer in answers]
    return document


def published_rehearsal() -> tuple[dict | None, str]:
    raw = db.session.execute(db.select(SiteSettings.value).where(SiteSettings.key == _KEY)).scalar_one_or_none()
    return (json.loads(raw) if raw else None), digest(raw)


def publish_rehearsal(document: dict, expected: str) -> bool:
    if db.session.get_bind().dialect.name == 'postgresql':
        db.session.execute(db.text('SELECT pg_advisory_xact_lock(:lock_id)'), {'lock_id': 624117042})
    current, revision = published_rehearsal()
    if revision != expected:
        raise StalePublication()
    if document == current:
        return False
    set_site_setting(_KEY, json.dumps(document, ensure_ascii=False, sort_keys=True))
    return True
