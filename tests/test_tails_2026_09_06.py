"""Tails closed on 2026-09-06 after the lesson audit items 11-16.

- api_auth_required logs a routine token rejection as one INFO line with the
  request path and User-Agent; unexpected errors keep the traceback.
- The plan progress bar no longer sends a stale localStorage token.
- Lesson ETAs follow measured durations; the SRS slot ETA scales with cards.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.daily_plan.items.curriculum import _DEFAULT_ETA_MINUTES, _LESSON_ETA_MINUTES
from app.daily_plan.items.srs import _srs_eta_minutes


class TestJwtLogging:
    def test_expired_or_bad_token_is_one_info_line(self, client, caplog):
        with caplog.at_level(logging.INFO, logger='app.api.decorators'):
            resp = client.get('/api/daily-status', headers={'Authorization': 'Bearer not.a.token', 'User-Agent': 'probe/1.0'})
        assert resp.status_code == 401
        records = [r for r in caplog.records if r.name == 'app.api.decorators']
        assert records, 'the rejection must be logged'
        assert all(r.levelno == logging.INFO for r in records)
        assert any('JWT rejected' in r.getMessage() and '/api/daily-status' in r.getMessage() and 'probe/1.0' in r.getMessage() for r in records)
        assert all(r.exc_info is None for r in records)

    def test_progress_bar_drops_the_stale_token(self):
        src = Path('app/templates/components/_daily_plan_progress.html').read_text(encoding='utf-8')
        assert "localStorage.getItem('jwt_token')" not in src
        assert "localStorage.removeItem('jwt_token')" in src
        assert 'Authorization' not in src


class TestEtaCalibration:
    def test_measured_types_are_short(self):
        assert _LESSON_ETA_MINUTES['vocabulary'] == 3
        assert _LESSON_ETA_MINUTES['final_test'] == 8
        assert _LESSON_ETA_MINUTES['translation'] == 10
        assert all(v >= 2 for v in _LESSON_ETA_MINUTES.values())
        assert max(_LESSON_ETA_MINUTES.values()) <= 10
        assert _DEFAULT_ETA_MINUTES == 4

    def test_srs_eta_scales_with_cards(self):
        assert _srs_eta_minutes(0) == 2
        assert _srs_eta_minutes(8) == 2
        assert _srs_eta_minutes(20) == 5
        assert _srs_eta_minutes(30) == 8
