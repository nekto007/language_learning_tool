"""Tests for the queued GA4 event helper."""
import pytest
from flask import session

from app.utils.gtag_events import queue_gtag_event, consume_gtag_events


def test_queue_and_consume(client):
    with client:
        client.get('/')
        queue_gtag_event('signup_completed', {'method': 'email'})
        events = consume_gtag_events()
        assert len(events) == 1
        assert events[0]['name'] == 'signup_completed'
        assert events[0]['params'] == {'method': 'email'}
        # Session entry should now be empty.
        assert session.get('_gtag_events') is None


def test_consume_empty(client):
    with client:
        client.get('/')
        assert consume_gtag_events() == []


def test_queue_caps_at_max(client):
    with client:
        client.get('/')
        for i in range(20):
            queue_gtag_event(f'event_{i}')
        events = consume_gtag_events()
        # Cap defends against session bloat.
        assert len(events) <= 8


def test_queue_rejects_empty_name(client):
    with client:
        client.get('/')
        queue_gtag_event('', {'method': 'email'})
        queue_gtag_event(None, {'method': 'email'})  # type: ignore[arg-type]
        assert consume_gtag_events() == []


def test_queue_strips_complex_params(client):
    """Lists, dicts, and other non-primitive params are dropped."""
    with client:
        client.get('/')
        queue_gtag_event(
            'test_event',
            {
                'good_str': 'value',
                'good_int': 42,
                'good_bool': True,
                'bad_list': [1, 2, 3],
                'bad_dict': {'nested': 'value'},
            },
        )
        events = consume_gtag_events()
        assert len(events) == 1
        params = events[0]['params']
        assert 'good_str' in params
        assert 'good_int' in params
        assert 'good_bool' in params
        assert 'bad_list' not in params
        assert 'bad_dict' not in params
