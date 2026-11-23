"""Metrica configuration and bounded, server-confirmed browser goals."""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit

from flask import current_app, request
from flask_login import current_user

METRIKA_HOSTS = frozenset({'llt-english.com', 'www.llt-english.com'})
GOALS_HEADER = 'X-LLT-Learning-Goals'
# Explicit hosts from Yandex's CSP documentation; no wildcard over yandex.ru.
_COLLECTOR_SUFFIXES = (
    'ru', 'az', 'by', 'co.il', 'com', 'com.am', 'com.ge', 'com.tr', 'ee',
    'fr', 'kg', 'kz', 'lt', 'lv', 'md', 'tj', 'tm', 'uz',
)
METRIKA_COLLECTORS = (
    *(f'https://mc.yandex.{s}' for s in _COLLECTOR_SUFFIXES),
    'https://mc.webvisor.com', 'https://mc.webvisor.org',
)
METRIKA_VIEWERS = (
    'https://metrika.yandex.ru', 'https://metrica.yandex.ru',
    'https://metrica.yandex.com', 'https://metrica.yandex.com.tr',
)
_PAGE_BLUEPRINTS = frozenset({
    'landing', 'words', 'study', 'learn', 'curriculum_lessons', 'book_courses',
    'grammar_lab', 'onboarding', 'legal', 'reader_words', 'books',
})
_PUBLIC_REPLAY_ENDPOINTS = frozenset({
    'landing.index', 'grammar_lab.index', 'grammar_lab.topics',
    'grammar_lab.topic_detail', 'words.public_word',
})
_UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')


def metrika_enabled() -> bool:
    """Never send local/test, admin, or another project's traffic."""
    value = str(current_app.config.get('YANDEX_METRIKA_ID', ''))
    return bool(
        re.fullmatch(r'[1-9][0-9]{0,14}', value)
        and not current_app.testing and not current_app.debug
        and request.is_secure
        and urlsplit(request.url_root).hostname in METRIKA_HOSTS
        and not (current_user.is_authenticated and current_user.is_admin)
        and not request.path.startswith(('/admin', '/api/'))
    )


def metrika_context() -> dict:
    endpoint = request.endpoint or ''
    if not metrika_enabled() or not (
        request.blueprint in _PAGE_BLUEPRINTS or endpoint in {'auth.login', 'auth.register'}
    ):
        return {'metrika': None}
    # Keep campaign attribution; omit search terms, email, next URLs and tokens.
    query = {
        key: request.args[key] for key in _UTM_KEYS
        if re.fullmatch(r'[A-Za-z0-9_.~-]{1,100}', request.args.get(key, ''))
    }
    page_url = request.base_url + ('?' + urlencode(query) if query else '')
    safe_referrer = ''
    try:
        referrer = urlsplit(request.referrer or '')
        if referrer.scheme in {'https', 'http'} and referrer.hostname:
            # Referrer paths can contain password-reset tokens too.
            safe_referrer = f'{referrer.scheme}://{referrer.hostname}/'
    except ValueError:
        pass
    replay = not current_user.is_authenticated and endpoint in _PUBLIC_REPLAY_ENDPOINTS
    return {'metrika': {
        'id': int(current_app.config['YANDEX_METRIKA_ID']),
        'options': {
            'ssr': True, 'webvisor': replay, 'clickmap': replay,
            'trackLinks': False, 'accurateTrackBounce': True,
            'url': page_url, 'referrer': safe_referrer,
        },
    }}


def add_learning_goals(response):
    """Only successful grading responses can notify the browser of learning.

    The body is unchanged. The browser reads a small same-origin response header
    without consuming/cloning the response stream or reading submitted answers.
    Native clients and failed requests never get analytics headers.
    """
    if (request.method != 'POST' or not 200 <= response.status_code < 300
            or not response.is_json or not metrika_enabled()):
        return response
    endpoint = request.endpoint
    if endpoint not in {
        'curriculum_lessons.submit_lesson', 'curriculum_lessons.update_lesson_progress',
        'curriculum_lessons.check_sentence_completion_item', 'curriculum_lessons.check_dictation_word',
        'grammar_lab.api_submit_answer',
    }:
        return response
    result = response.get_json(silent=True)
    if not isinstance(result, dict) or result.get('error') or result.get('success') is False:
        return response
    goals = []
    if endpoint == 'grammar_lab.api_submit_answer':
        if type(result.get('is_correct')) is bool:
            goals.append('learning_answered')
    elif endpoint in {
        'curriculum_lessons.check_sentence_completion_item', 'curriculum_lessons.check_dictation_word',
    }:
        if type(result.get('correct')) is bool:
            goals.append('learning_answered')
    elif endpoint == 'curriculum_lessons.update_lesson_progress':
        progress = result.get('progress')
        if isinstance(progress, dict) and progress.get('status') == 'completed':
            goals.append('lesson_completed')
    else:
        if type(result.get('passed')) is bool or type(result.get('score')) in {int, float}:
            goals.append('learning_answered')
        if result.get('passed') is True or result.get('completed') is True:
            goals.append('lesson_completed')
    if goals:
        response.headers[GOALS_HEADER] = ','.join(goals)
    return response


def init_metrika(app):
    app.context_processor(metrika_context)
    app.after_request(add_learning_goals)
