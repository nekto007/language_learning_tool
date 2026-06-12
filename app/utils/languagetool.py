"""LanguageTool client — грамматическая проверка письменных работ.

Self-hosted LanguageTool (https://languagetool.org), HTTP API ``/v2/check``.
Включается переменной окружения ``LANGUAGETOOL_URL``
(например ``http://localhost:8010``); без неё проверка выключена и все
вызовы тихо возвращают None — письмо работает как раньше.

Запуск сервера локально/на проде:
    docker run -d --name languagetool -p 8010:8010 erikvl87/languagetool

Дизайн: best-effort. Любая ошибка (сервер лежит, таймаут, кривой JSON) →
None, submit письма никогда не блокируется проверкой.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from flask import current_app

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 6
MAX_TEXT_LENGTH = 20000
MAX_MATCHES = 50
MAX_REPLACEMENTS = 3

# LT category id → русская метка для UI. Незнакомая категория падает
# обратно на category name из ответа.
CATEGORY_LABELS_RU = {
    'TYPOS': 'Орфография',
    'GRAMMAR': 'Грамматика',
    'PUNCTUATION': 'Пунктуация',
    'CASING': 'Регистр',
    'TYPOGRAPHY': 'Типографика',
    'STYLE': 'Стиль',
    'CONFUSED_WORDS': 'Похожие слова',
    'REDUNDANCY': 'Избыточность',
    'COLLOCATIONS': 'Сочетаемость',
    'COMPOUNDING': 'Слитное написание',
    'SEMANTICS': 'Смысл',
    'MISC': 'Прочее',
    'AMERICAN_ENGLISH_STYLE': 'Стиль (AmE)',
    'BRITISH_ENGLISH': 'Стиль (BrE)',
    'NONSTANDARD_PHRASES': 'Нестандартные фразы',
    'FALSE_FRIENDS': 'Ложные друзья переводчика',
}


def get_languagetool_url() -> str:
    """Базовый URL LT-сервера из конфига; '' = проверка выключена."""
    try:
        return (current_app.config.get('LANGUAGETOOL_URL') or '').rstrip('/')
    except RuntimeError:
        # Вне app-контекста (например, скрипты) — выключено.
        return ''


def is_languagetool_enabled() -> bool:
    return bool(get_languagetool_url())


def check_text(
    text: str,
    language: str = 'en-US',
    mother_tongue: str = 'ru',
) -> Optional[dict]:
    """Проверить текст; вернуть {'error_count': N, 'matches': [...]} или None.

    None = проверка недоступна (выключена/упала) — caller показывает письмо
    без грамматического фидбека. Пустой текст тоже None.

    Каждый match: offset/length (позиции в исходном тексте для подсветки),
    message, replacements (до 3 предложенных исправлений), category_label
    (русская метка категории), rule_id.
    """
    base_url = get_languagetool_url()
    if not base_url or not text or not text.strip():
        return None

    try:
        response = requests.post(
            f'{base_url}/v2/check',
            data={
                'text': text[:MAX_TEXT_LENGTH],
                'language': language,
                'motherTongue': mother_tongue,
            },
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("LanguageTool check failed: %s", exc)
        return None

    raw_matches = payload.get('matches')
    if not isinstance(raw_matches, list):
        return None

    matches = []
    for raw in raw_matches[:MAX_MATCHES]:
        try:
            rule = raw.get('rule') or {}
            category = rule.get('category') or {}
            category_id = category.get('id') or 'MISC'
            matches.append({
                'offset': int(raw['offset']),
                'length': int(raw['length']),
                'message': str(raw.get('message') or '')[:300],
                'short_message': str(raw.get('shortMessage') or '')[:100],
                'replacements': [
                    str(r.get('value') or '')[:100]
                    for r in (raw.get('replacements') or [])[:MAX_REPLACEMENTS]
                ],
                'rule_id': str(rule.get('id') or '')[:100],
                'category_id': str(category_id)[:50],
                'category_label': CATEGORY_LABELS_RU.get(
                    category_id, str(category.get('name') or category_id)[:50]
                ),
            })
        except (KeyError, TypeError, ValueError):
            continue

    return {'error_count': len(matches), 'matches': matches}
