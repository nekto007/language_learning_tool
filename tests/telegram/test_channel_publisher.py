"""Tests for the Telegram channel auto-publisher."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.admin.site_settings import set_site_setting
from app.grammar_lab.models import GrammarTopic
from app.telegram.channel_models import (
    ChannelPost, KIND_GRAMMAR, KIND_WORD,
    STATUS_FAILED, STATUS_PUBLISHED, STATUS_QUEUED, STATUS_SKIPPED,
)
from app.telegram.channel_publisher import (
    format_grammar_post, format_word_post,
    get_channel_config, pick_next_grammar_topic, pick_next_word,
    publish_due, queue_upcoming,
)
from app.words.models import CollectionWords


# ─── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def candidate_word(db_session):
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'channel_word_{suffix}',
        russian_word='тестовое слово',
        item_type='word',
        level='A1',
        ipa_transcription='ˈtestˌwɜrd',
        frequency_rank=100,
    )
    db_session.add(word)
    db_session.commit()
    return word


@pytest.fixture
def candidate_topic(db_session):
    suffix = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'channel-topic-{suffix}',
        title='Test Topic',
        title_ru='Тестовая тема',
        level='A1',
        order=1,
        content={
            'introduction': 'Эта тема рассказывает про настоящее время.',
            'common_mistakes': [
                {'wrong': 'I goes home', 'correct': 'I go home'},
            ],
        },
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def configured_channel(db_session):
    """Configure a channel id so the publisher actually queues/sends."""
    set_site_setting('telegram_channel_id', '-1001234567890', db_session=db_session)
    db_session.commit()
    yield
    set_site_setting('telegram_channel_id', '', db_session=db_session)
    db_session.commit()


# ─── Pickers ────────────────────────────────────────────────────────────


def test_pick_next_word_returns_eligible(db_session, candidate_word):
    picked = pick_next_word(db_session, dedup_days=90)
    assert picked is not None
    assert picked.russian_word
    assert picked.ipa_transcription


def test_pick_next_word_skips_recent(db_session, candidate_word):
    post = ChannelPost(
        kind=KIND_WORD,
        content_ref_type='word',
        content_ref_id=candidate_word.id,
        scheduled_for=datetime.utcnow() - timedelta(hours=1),
        status=STATUS_PUBLISHED,
        text_snapshot='snapshot',
    )
    db_session.add(post)
    db_session.commit()

    picked = pick_next_word(db_session, dedup_days=90)
    assert picked is None or picked.id != candidate_word.id


def test_pick_next_grammar_topic_returns_eligible(db_session, candidate_topic):
    picked = pick_next_grammar_topic(db_session, dedup_days=90)
    assert picked is not None


def test_pick_next_grammar_topic_skips_recent(db_session, candidate_topic):
    post = ChannelPost(
        kind=KIND_GRAMMAR,
        content_ref_type='grammar_topic',
        content_ref_id=candidate_topic.id,
        scheduled_for=datetime.utcnow() - timedelta(days=1),
        status=STATUS_PUBLISHED,
        text_snapshot='snapshot',
    )
    db_session.add(post)
    db_session.commit()

    picked = pick_next_grammar_topic(db_session, dedup_days=90)
    assert picked is None or picked.id != candidate_topic.id


# ─── Formatters ─────────────────────────────────────────────────────────


def test_format_word_post_contains_key_fields(candidate_word):
    text = format_word_post(candidate_word, site_url='https://llt-english.com')
    assert 'Слово дня' in text
    assert candidate_word.english_word in text
    assert candidate_word.russian_word in text
    assert candidate_word.ipa_transcription in text
    assert 'A1' in text
    assert '/dictionary/' in text


def test_format_word_post_escapes_html(db_session):
    suffix = uuid.uuid4().hex[:6]
    nasty = CollectionWords(
        english_word=f'<script>{suffix}',
        russian_word='<b>evil</b>',
        item_type='word',
        level='A1',
        ipa_transcription='x',
    )
    db_session.add(nasty)
    db_session.commit()
    text = format_word_post(nasty)
    assert '<script>' not in text  # raw tag must be escaped
    assert '&lt;script&gt;' in text
    assert '&lt;b&gt;evil&lt;/b&gt;' in text


def test_format_word_post_converts_br_to_newline(db_session):
    """word.sentences contains web-style <br>; channel post must turn that
    into a real line break so Telegram doesn't show '<br>' literally."""
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'br_word_{suffix}',
        russian_word='тест',
        item_type='word',
        level='A1',
        ipa_transcription='x',
        sentences='I am ready.<br>Я готов.',
    )
    db_session.add(word)
    db_session.commit()
    text = format_word_post(word)
    assert '<br>' not in text
    assert '&lt;br&gt;' not in text
    assert 'I am ready.' in text
    assert 'Я готов.' in text


def test_format_word_post_strips_other_html(db_session):
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'span_word_{suffix}',
        russian_word='тест',
        item_type='word',
        level='A1',
        ipa_transcription='x',
        sentences='<span class="x">hello</span><br><em>привет</em>',
    )
    db_session.add(word)
    db_session.commit()
    text = format_word_post(word)
    assert '<span' not in text and '&lt;span' not in text
    assert '<em>' not in text and '&lt;em&gt;' not in text
    assert 'hello' in text
    assert 'привет' in text


def test_format_grammar_post_includes_common_mistake(candidate_topic):
    text = format_grammar_post(candidate_topic, site_url='https://llt-english.com')
    assert 'Грамматика' in text
    assert candidate_topic.title_ru in text
    assert 'Частая ошибка' in text
    assert 'I goes home' in text
    assert 'I go home' in text
    assert '/grammar-lab/topic/' in text


def test_format_word_post_includes_mini_practice_and_action_cta(candidate_word):
    text = format_word_post(candidate_word)
    assert 'Мини-практика' in text
    assert candidate_word.english_word in text
    # Action-oriented CTA — must mention произношение/карточк.
    assert 'Послушай' in text or 'послушай' in text.lower()
    assert 'карточк' in text


def test_format_grammar_post_examples_appear_before_theory(db_session):
    """Live examples must surface above the abstract introduction text."""
    suffix = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'examples-first-{suffix}', title='Examples first',
        title_ru='Сначала примеры',
        level='A2', order=1,
        content={
            'introduction': 'ZZZ-INTRO теория про конструкции.',
            'sections': [
                {'examples': [
                    {'en': 'I have a glass of water.', 'ru': 'У меня стакан воды.'},
                    {'en': 'She drinks a cup of tea.', 'ru': 'Она пьёт чашку чая.'},
                ]},
            ],
        },
    )
    db_session.add(topic)
    db_session.commit()
    text = format_grammar_post(topic)
    assert 'glass of water' in text
    assert text.index('glass of water') < text.index('ZZZ-INTRO')


def test_format_grammar_post_includes_mini_practice_and_action_cta(candidate_topic):
    text = format_grammar_post(candidate_topic)
    assert 'Мини-практика' in text
    assert 'упражнения' in text.lower() or 'упражнениях' in text.lower()


def test_format_grammar_post_without_optional_fields(db_session):
    suffix = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'bare-{suffix}', title='Bare', title_ru='Голая тема',
        level='B1', order=99, content={},
    )
    db_session.add(topic)
    db_session.commit()
    text = format_grammar_post(topic)
    assert 'Голая тема' in text
    assert 'Частая ошибка' not in text  # no mistakes -> no section


# ─── Queueing ───────────────────────────────────────────────────────────


def test_queue_upcoming_noop_without_channel(db_session, candidate_word, candidate_topic):
    """No channel id → no rows created (avoid building a queue that will never fire)."""
    set_site_setting('telegram_channel_id', '', db_session=db_session)
    db_session.commit()
    created = queue_upcoming(db_session=db_session, days_ahead=2)
    assert created == []


def test_queue_upcoming_creates_slots(db_session, candidate_word, candidate_topic, configured_channel):
    created = queue_upcoming(db_session=db_session, days_ahead=2)
    # 2 days × 2 slots = up to 4 posts (may be fewer if today's slots already past)
    assert 1 <= len(created) <= 4
    for post in created:
        assert post.kind in (KIND_WORD, KIND_GRAMMAR)
        assert post.status == STATUS_QUEUED
        assert post.text_snapshot
        assert post.scheduled_for > datetime.utcnow()


def test_queue_upcoming_is_idempotent(db_session, candidate_word, candidate_topic, configured_channel):
    first = queue_upcoming(db_session=db_session, days_ahead=2)
    second = queue_upcoming(db_session=db_session, days_ahead=2)
    # Second call must not duplicate the first call's slots.
    assert second == [] or all(p.id not in {f.id for f in first} for p in second)


def test_queue_upcoming_respects_minutes(
    db_session, candidate_word, candidate_topic, configured_channel,
):
    """Configured minute is reflected in scheduled_for, not zeroed out."""
    set_site_setting('telegram_channel_morning_utc_hour', '9', db_session=db_session)
    set_site_setting('telegram_channel_morning_utc_minute', '20', db_session=db_session)
    set_site_setting('telegram_channel_evening_utc_hour', '18', db_session=db_session)
    set_site_setting('telegram_channel_evening_utc_minute', '45', db_session=db_session)
    db_session.commit()

    created = queue_upcoming(db_session=db_session, days_ahead=2)
    minutes = {p.scheduled_for.minute for p in created}
    # Either 20 or 45 must appear (today's slots may already be in the past).
    assert minutes.issubset({20, 45})
    assert minutes  # at least one slot was queued

    # Cleanup so other tests aren't polluted.
    set_site_setting('telegram_channel_morning_utc_minute', '0', db_session=db_session)
    set_site_setting('telegram_channel_evening_utc_minute', '0', db_session=db_session)
    db_session.commit()


# ─── Publishing ─────────────────────────────────────────────────────────


def test_publish_due_skips_when_channel_missing(db_session, candidate_word):
    """Queued posts get marked SKIPPED when channel id is unset at publish time."""
    set_site_setting('telegram_channel_id', '', db_session=db_session)
    post = ChannelPost(
        kind=KIND_WORD,
        content_ref_type='word',
        content_ref_id=candidate_word.id,
        scheduled_for=datetime.utcnow() - timedelta(minutes=1),
        status=STATUS_QUEUED,
        text_snapshot=format_word_post(candidate_word),
    )
    db_session.add(post)
    db_session.commit()

    result = publish_due(db_session=db_session)
    assert result['skipped_no_channel'] == 1
    db_session.refresh(post)
    assert post.status == STATUS_SKIPPED


def test_publish_due_sends_and_marks_published(
    db_session, app, candidate_word, configured_channel,
):
    """Mock the HTTP call: status flips to PUBLISHED and message_id is stored."""
    app.config['TELEGRAM_BOT_TOKEN'] = 'fake-test-token'
    post = ChannelPost(
        kind=KIND_WORD,
        content_ref_type='word',
        content_ref_id=candidate_word.id,
        scheduled_for=datetime.utcnow() - timedelta(minutes=1),
        status=STATUS_QUEUED,
        text_snapshot=format_word_post(candidate_word),
    )
    db_session.add(post)
    db_session.commit()

    fake_resp = SimpleNamespace(
        ok=True,
        status_code=200,
        content=b'{"ok":true,"result":{"message_id":42}}',
        text='ok',
    )
    fake_resp.json = lambda: {'ok': True, 'result': {'message_id': 42}}
    with patch('app.telegram.channel_publisher.requests.post', return_value=fake_resp):
        result = publish_due(db_session=db_session)

    assert result['sent'] == 1
    assert result['failed'] == 0
    db_session.refresh(post)
    assert post.status == STATUS_PUBLISHED
    assert post.message_id == 42
    assert post.published_at is not None


def test_publish_due_records_failure(
    db_session, app, candidate_word, configured_channel,
):
    """Non-200 response flips status to FAILED with an error message."""
    app.config['TELEGRAM_BOT_TOKEN'] = 'fake-test-token'
    post = ChannelPost(
        kind=KIND_WORD,
        content_ref_type='word',
        content_ref_id=candidate_word.id,
        scheduled_for=datetime.utcnow() - timedelta(minutes=1),
        status=STATUS_QUEUED,
        text_snapshot=format_word_post(candidate_word),
    )
    db_session.add(post)
    db_session.commit()

    fake_resp = SimpleNamespace(
        ok=False,
        status_code=400,
        content=b'{"ok":false,"description":"chat not found"}',
        text='{"ok":false,"description":"chat not found"}',
    )
    fake_resp.json = lambda: {'ok': False, 'description': 'chat not found'}
    with patch('app.telegram.channel_publisher.requests.post', return_value=fake_resp):
        result = publish_due(db_session=db_session)

    assert result['failed'] == 1
    db_session.refresh(post)
    assert post.status == STATUS_FAILED
    assert post.error and 'chat not found' in post.error


def test_publish_due_treats_200_with_ok_false_as_failure(
    db_session, app, candidate_word, configured_channel,
):
    """Regression: Telegram sometimes returns HTTP 200 with ok=false.

    The previous publisher trusted resp.ok and marked the post PUBLISHED,
    so the row showed a phantom message_id while nothing landed in the
    channel. The fix is to also check body['ok'].
    """
    app.config['TELEGRAM_BOT_TOKEN'] = 'fake-test-token'
    post = ChannelPost(
        kind=KIND_WORD,
        content_ref_type='word',
        content_ref_id=candidate_word.id,
        scheduled_for=datetime.utcnow() - timedelta(minutes=1),
        status=STATUS_QUEUED,
        text_snapshot=format_word_post(candidate_word),
    )
    db_session.add(post)
    db_session.commit()

    fake_resp = SimpleNamespace(
        ok=True,
        status_code=200,
        content=b'{"ok":false,"description":"Bad Request: chat not found"}',
        text='{"ok":false,"description":"Bad Request: chat not found"}',
    )
    fake_resp.json = lambda: {'ok': False, 'description': 'Bad Request: chat not found'}
    with patch('app.telegram.channel_publisher.requests.post', return_value=fake_resp):
        result = publish_due(db_session=db_session)

    assert result['failed'] == 1
    assert result['sent'] == 0
    db_session.refresh(post)
    assert post.status == STATUS_FAILED
    assert post.error and 'chat not found' in post.error


# ─── Admin route ────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_admin_telegram_channel_page(admin_client, db_session):
    response = admin_client.get('/admin/telegram-channel')
    assert response.status_code == 200
    assert b'Telegram' in response.data


def test_admin_telegram_channel_rejects_non_admin(client):
    response = client.get('/admin/telegram-channel')
    assert response.status_code in (302, 401, 403)
