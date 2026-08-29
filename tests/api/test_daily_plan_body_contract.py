"""Контракт тела запроса и параметра `tz` в зоне «План дня» (кластер C фазы 2).

Находки `DP-079`, `DP-081`, `DP-102`, `DP-103` реестра
`docs/audit/2026-08-26-daily-plan-audit.md`: там, где по контракту зоны должен
быть `400` с телом `api_error`, приходила `500`.

- `DP-079`: `request.get_json(silent=True) or {}` переживает валидный
  не-объект (`[1]`, `"строка"`, `42`) — следующий `.get()` даёт
  `AttributeError`.
- `DP-081`: `/events` — `event_type` unhashable, `plan_date` не строка,
  `meta` не dict.
- `DP-103`: битый JSON молча становился `{}` и рапортовался как ошибка ПОЛЯ.
- `DP-102`: `?tz=` длиной ≥256 роняет `_validate_timezone` через `OSError`,
  который не ловится `except (KeyError, ValueError)`.
"""
from __future__ import annotations

import pytest


# Каждый POST-эндпоинт зоны. Пять из них тело реально читают (список ниже, в
# `test_body_readers_answer_400_invalid_body`); `/api/plan/resume` и
# `/api/streak/repair` тела не читают вовсе и включены как страж «здесь тоже
# нет 500», а не как покрытие `_json_object_body`.
ZONE_POST_ENDPOINTS = [
    '/api/daily-plan/events',
    '/api/daily-plan/error-review/complete',
    '/api/daily-plan/phrase-review/complete',
    '/api/plan/pause',
    '/api/plan/resume',
    '/api/streak/repair',
    '/api/daily-plan/challenge/complete',
    '/api/daily-plan/skip-lesson',
]

# Валидный JSON, который не является объектом.
NON_OBJECT_BODIES = [
    ('list', '[1]'),
    ('string', '"строка"'),
    ('number', '42'),
    ('bool', 'true'),
    ('null', 'null'),
]


def _post_raw(client, url: str, data: str):
    return client.post(url, data=data, content_type='application/json')


# ---------------------------------------------------------------------------
# DP-079: валидный не-объект в теле
# ---------------------------------------------------------------------------


class TestNonObjectBodyIsRejected:
    """`[1]`/`"s"`/`42` — правдивый JSON, но не объект: 400, а не 500."""

    @pytest.mark.parametrize('url', ZONE_POST_ENDPOINTS)
    @pytest.mark.parametrize('label,raw', NON_OBJECT_BODIES)
    def test_no_500_on_non_object_body(
        self, authenticated_client, db_session, url, label, raw,
    ):
        resp = _post_raw(authenticated_client, url, raw)
        assert resp.status_code < 500, (
            f'{url} ответил {resp.status_code} на тело {label}'
        )

    @pytest.mark.parametrize('url', [
        '/api/daily-plan/events',
        '/api/daily-plan/error-review/complete',
        '/api/plan/pause',
        '/api/daily-plan/challenge/complete',
        '/api/daily-plan/skip-lesson',
    ])
    @pytest.mark.parametrize('label,raw', NON_OBJECT_BODIES)
    def test_body_readers_answer_400_invalid_body(
        self, authenticated_client, db_session, url, label, raw,
    ):
        """Роуты, которые тело реально читают, называют причину явно."""
        resp = _post_raw(authenticated_client, url, raw)
        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload['success'] is False
        assert payload['error'] == 'invalid_body'
        assert payload['status'] == 400


# ---------------------------------------------------------------------------
# DP-103: битый JSON отличается от «нет поля»
# ---------------------------------------------------------------------------


class TestBrokenJsonIsNamedAsSuch:
    """Не-JSON под `Content-Type: application/json` — `invalid_json`, не поле."""

    @pytest.mark.parametrize('url', ZONE_POST_ENDPOINTS)
    def test_no_500_on_broken_json(self, authenticated_client, db_session, url):
        resp = _post_raw(authenticated_client, url, '{"event_type": ')
        assert resp.status_code < 500

    @pytest.mark.parametrize('url', [
        '/api/daily-plan/events',
        '/api/daily-plan/error-review/complete',
        '/api/plan/pause',
        '/api/daily-plan/challenge/complete',
        '/api/daily-plan/skip-lesson',
    ])
    def test_broken_json_reports_invalid_json(
        self, authenticated_client, db_session, url,
    ):
        resp = _post_raw(authenticated_client, url, '{"event_type": ')
        assert resp.status_code == 400
        payload = resp.get_json()
        assert payload['error'] == 'invalid_json', (
            f'{url} назвал битый JSON ошибкой поля: {payload}'
        )


class TestMissingBodyStillBehavesAsEmptyObject:
    """Отсутствие тела — не «битый JSON»: прежний контракт полей сохраняется."""

    def test_pause_without_body_reports_missing_field(
        self, authenticated_client, db_session,
    ):
        resp = authenticated_client.post('/api/plan/pause')
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_days'

    def test_error_review_without_body_reports_missing_field(
        self, authenticated_client, db_session,
    ):
        resp = authenticated_client.post('/api/daily-plan/error-review/complete')
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'no_errors_submitted'

    def test_empty_json_object_is_accepted_as_body(
        self, authenticated_client, db_session,
    ):
        resp = _post_raw(authenticated_client, '/api/plan/pause', '{}')
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_days'

    def test_form_body_is_still_invalid_content_type(
        self, authenticated_client, db_session,
    ):
        resp = authenticated_client.post(
            '/api/daily-plan/events',
            data='event_type=next_step_shown',
            content_type='application/x-www-form-urlencoded',
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_content_type'


# ---------------------------------------------------------------------------
# DP-081: типовые путаницы в полях /events
# ---------------------------------------------------------------------------


class TestEventsFieldConfusions:
    """Три подтверждённых механизма 500 на `/daily-plan/events`."""

    @pytest.mark.parametrize('event_type', [{}, [], 42, None, {'a': 1}])
    def test_unhashable_or_non_string_event_type(
        self, authenticated_client, db_session, event_type,
    ):
        resp = authenticated_client.post(
            '/api/daily-plan/events', json={'event_type': event_type},
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_event_type'

    @pytest.mark.parametrize('plan_date', [42, {}, [], True, 3.5])
    def test_non_string_plan_date_falls_back_to_today(
        self, authenticated_client, db_session, test_user, plan_date,
    ):
        """Не строка — тот же класс, что неразбираемая строка: молча сегодня."""
        from app.daily_plan.models import DailyPlanEvent
        from app.utils.db import db as real_db
        from app.utils.time_utils import get_user_local_date

        resp = authenticated_client.post('/api/daily-plan/events', json={
            'event_type': 'next_step_dismissed',
            'plan_date': plan_date,
        })
        assert resp.status_code == 200

        # 200 сам по себе ничего не доказывает: запись с чужой датой (или её
        # отсутствие) тоже даёт 200.
        db_session.expire_all()
        rows = DailyPlanEvent.query.filter_by(
            user_id=test_user.id, event_type='next_step_dismissed',
        ).all()
        assert len(rows) == 1
        assert rows[0].plan_date == get_user_local_date(test_user.id, real_db)

    @pytest.mark.parametrize('meta', [[1], 'x', 42, True])
    def test_non_dict_meta_is_ignored(self, authenticated_client, db_session, meta):
        resp = authenticated_client.post('/api/daily-plan/events', json={
            'event_type': 'next_step_shown',
            'meta': meta,
        })
        assert resp.status_code == 200

    def test_non_dict_meta_does_not_smuggle_slot_skip(
        self, authenticated_client, db_session,
    ):
        """`slot_skipped` без разбираемого `step_kind` — 400, а не падение."""
        resp = authenticated_client.post('/api/daily-plan/events', json={
            'event_type': 'slot_skipped',
            'meta': [1],
        })
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_slot_kind'

    @pytest.mark.parametrize('step_kind', [{'a': 1}, [1], 42])
    def test_non_string_step_kind_is_rejected_not_crashed(
        self, authenticated_client, db_session, step_kind,
    ):
        resp = authenticated_client.post('/api/daily-plan/events', json={
            'event_type': 'slot_skipped',
            'step_kind': step_kind,
            'reason_text': 'no_time',
        })
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_slot_kind'


# ---------------------------------------------------------------------------
# DP-102: `?tz=` не роняет валидатор
# ---------------------------------------------------------------------------


TZ_ENDPOINTS = ['/api/daily-status', '/api/daily-plan', '/api/daily-summary']


class TestTimezoneParamNeverCrashes:
    """`_validate_timezone` — фолбэк на дефолт, а не 500."""

    @pytest.mark.parametrize('url', TZ_ENDPOINTS)
    @pytest.mark.parametrize('tz', [
        'A' * 300,          # OSError [Errno 63] File name too long
        'A' * 64,           # длинное, но в пределах имени файла
        '',                 # пусто
        '../../etc/passwd',  # обход каталога
        'Not/A/Zone',
        '\x00Europe/Moscow',
    ])
    def test_hostile_tz_is_not_a_500(self, authenticated_client, db_session, url, tz):
        resp = authenticated_client.get(url, query_string={'tz': tz})
        assert resp.status_code < 500, f'{url}?tz=<{len(tz)} chars> → {resp.status_code}'

    def test_validator_returns_default_for_overlong_name(self):
        from app.api.daily_plan import DEFAULT_TZ, _validate_timezone

        assert _validate_timezone('A' * 300) == DEFAULT_TZ

    @pytest.mark.parametrize('value', [None, 42, [], {}, True])
    def test_validator_returns_default_for_non_string(self, value):
        from app.api.daily_plan import DEFAULT_TZ, _validate_timezone

        assert _validate_timezone(value) == DEFAULT_TZ

    def test_validator_keeps_real_zone(self):
        from app.api.daily_plan import _validate_timezone

        assert _validate_timezone('Europe/Istanbul') == 'Europe/Istanbul'


# ---------------------------------------------------------------------------
# DP-079 на `/phrase-review/complete`: гейт сессии стоит ПЕРЕД разбором тела
# ---------------------------------------------------------------------------


class TestPhraseReviewBodyContract:
    """Без засеянной сессии роут отвечает `phrase_review_expired` до разбора тела.

    Поэтому параметризованные кейсы выше его контракт тела не проверяют:
    возврат к `request.get_json(silent=True) or {}` восстановил бы 500 на
    `[1].get('answers')` при зелёном наборе.
    """

    @staticmethod
    def _seed(client):
        with client.session_transaction() as sess:
            sess['daily_phrase_review_items'] = [{
                'id': 'phrase:1',
                'prompt': 'Скажите это по-английски.',
                'answer': 'I love you',
                'accepted_answers': ['I love you'],
                'source': 'recent_module',
                'error_id': None,
            }]

    @pytest.mark.parametrize('label,raw', NON_OBJECT_BODIES)
    def test_non_object_body_is_400_invalid_body(
        self, authenticated_client, db_session, label, raw,
    ):
        self._seed(authenticated_client)
        resp = _post_raw(
            authenticated_client, '/api/daily-plan/phrase-review/complete', raw,
        )
        assert resp.status_code == 400, f'тело {label} → {resp.status_code}'
        assert resp.get_json()['error'] == 'invalid_body'

    def test_broken_json_is_400_invalid_json(self, authenticated_client, db_session):
        self._seed(authenticated_client)
        resp = _post_raw(
            authenticated_client,
            '/api/daily-plan/phrase-review/complete',
            '{"answers": ',
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_json'

    def test_non_list_answers_is_named_explicitly(
        self, authenticated_client, db_session,
    ):
        self._seed(authenticated_client)
        resp = authenticated_client.post(
            '/api/daily-plan/phrase-review/complete', json={'answers': {'a': 1}},
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_answers'
