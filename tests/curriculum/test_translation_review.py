"""Rubric review proves explicit comparison without claiming automatic accuracy."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask
from itsdangerous.timed import TimestampSigner

from app.curriculum.translation_review import review_item, review_submission

CANONICAL = 'The investigative team spent six months verifying the anonymous documents.'
PARAPHRASE = 'The investigative team spent half a year verifying the anonymous documents.'


@pytest.fixture
def review_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'local-review-unit-test-key'
    with app.app_context():
        yield app


@pytest.fixture
def lesson():
    return SimpleNamespace(id=42, type='translation', content_version=3, content={
        'mode': 'rubric', 'items': [
            {'russian': 'Команда проверяла документы полгода.', 'english': CANONICAL,
             'alternatives': [CANONICAL, 'For six months, the team verified the anonymous documents.'],
             'hint_words': ['investigative', 'anonymous'], 'editorial_note': 'Keep all raw fields in proof'},
            {'russian': 'Стороны провели переговоры до подписания договора.',
             'english': 'Both sides negotiated before signing the contract.'},
        ],
    })


def _project(lesson):
    return [{'russian': item['russian'], 'english': item['english'],
             'alternatives': item.get('alternatives') or [], 'hint_words': item.get('hint_words') or []}
            for item in lesson.content['items']]


def _confirmed(lesson):
    pending = review_item(lesson, 7, 0, PARAPHRASE)
    return review_item(lesson, 7, 0, PARAPHRASE, review_token=pending['review_token'], confirm=True)


@pytest.mark.parametrize('answer', [CANONICAL, 'For six months, the team verified the anonymous documents.'])
def test_authored_variants_remain_automatic_matches(review_app, lesson, answer):
    result = review_item(lesson, 7, 0, answer)
    assert result['status'] == 'matched'
    assert result['correct'] is True
    assert result['review_token'] is None


def test_unknown_answer_needs_reference_review_without_false_zero(review_app, lesson):
    result = review_item(lesson, 7, 0, PARAPHRASE)
    assert result['success'] is True
    assert result['status'] == 'needs_review'
    assert result['correct'] is None
    assert 'score' not in result
    assert result['reference_answer'] == CANONICAL
    assert result['review_token']


def test_confirmation_issues_distinct_reviewed_proof(review_app, lesson):
    pending = review_item(lesson, 7, 0, PARAPHRASE)
    result = review_item(lesson, 7, 0, PARAPHRASE, review_token=pending['review_token'], confirm=True)
    assert result['status'] == 'self_reviewed'
    assert result['correct'] is None
    assert result['review_token'] != pending['review_token']
    assert review_item(lesson, 7, 0, PARAPHRASE,
                       review_token=result['review_token'], confirm=True)['status'] == 'self_reviewed'


@pytest.mark.parametrize('token', [None, True, 'forged-token', {'confirmed': True}])
def test_confirmation_requires_valid_signed_proof(review_app, lesson, token):
    result = review_item(lesson, 7, 0, PARAPHRASE, review_token=token, confirm=True)
    assert result['success'] is False
    assert result['error'] == 'invalid_review_token'


@pytest.mark.parametrize('change', ['user', 'lesson', 'version', 'item', 'answer', 'index'])
def test_pending_proof_cannot_be_reused_for_changed_context(review_app, lesson, change):
    token = review_item(lesson, 7, 0, PARAPHRASE)['review_token']
    other = deepcopy(lesson)
    uid, index, answer = 7, 0, PARAPHRASE
    if change == 'user':
        uid = 8
    elif change == 'lesson':
        other.id = 43
    elif change == 'version':
        other.content_version = 4
    elif change == 'item':
        other.content['items'][0]['editorial_note'] = 'Changed field absent from route projection'
    elif change == 'answer':
        answer = 'The team verified the anonymous documents for half a year.'
    else:
        index = 1
    result = review_item(other, uid, index, answer, review_token=token, confirm=True)
    assert result['success'] is False
    assert result['error'] == 'invalid_review_token'


def test_pending_proof_expires_after_one_hour(review_app, lesson):
    with patch.object(TimestampSigner, 'get_timestamp', return_value=100_000):
        token = review_item(lesson, 7, 0, PARAPHRASE)['review_token']
    with patch.object(TimestampSigner, 'get_timestamp', return_value=103_601):
        assert review_item(lesson, 7, 0, PARAPHRASE, review_token=token, confirm=True)['error'] == 'invalid_review_token'


@pytest.mark.parametrize('answer', ['', '   ', 'Только русский ответ.', 'hello', 'x' * 2001, None, ['hello world']])
def test_blank_non_english_short_and_oversize_answers_cannot_be_reviewed(review_app, lesson, answer):
    assert review_item(lesson, 7, 0, answer)['error'] == 'invalid_answer'


@pytest.mark.parametrize('mode', ['guided', None])
def test_review_cannot_weaken_nonrubric_mode(review_app, lesson, mode):
    lesson.content['mode'] = mode
    assert review_item(lesson, 7, 0, CANONICAL)['error'] == 'unsupported_mode'
    result = review_submission(lesson, 7, _project(lesson), [PARAPHRASE, 'Any other sentence.'], [])
    assert result['success'] is False
    assert result['completed'] is False
    assert result['score'] is None


def test_open_translation_also_supports_honest_review_of_unknown_variants(review_app, lesson):
    lesson.content['mode'] = 'open'
    assert review_item(lesson, 7, 0, CANONICAL)['status'] == 'matched'
    pending = review_item(lesson, 7, 0, PARAPHRASE)
    assert pending['status'] == 'needs_review'
    reviewed = review_item(lesson, 7, 0, PARAPHRASE, review_token=pending['review_token'], confirm=True)
    assert reviewed['status'] == 'self_reviewed'


def test_submission_requires_completed_review_not_pending_token(review_app, lesson):
    pending = review_item(lesson, 7, 0, PARAPHRASE)
    answers = [PARAPHRASE, lesson.content['items'][1]['english']]
    result = review_submission(lesson, 7, _project(lesson), answers, [pending['review_token'], None])
    assert result['success'] is False
    assert result['completed'] is False
    assert result['score'] is None
    assert result['error'] == 'invalid_review_token'


def test_submission_without_proofs_returns_review_required_and_references(review_app, lesson):
    result = review_submission(lesson, 7, _project(lesson),
                               [PARAPHRASE, lesson.content['items'][1]['english']], [])
    assert result['error'] == 'review_required'
    assert result['correct_items'] == 1
    assert result['reviewed_items'] == []
    assert result['item_results'][0]['reference_answer'] == CANONICAL
    assert result['item_results'][0]['status'] == 'needs_review'


def test_valid_submission_records_self_review_without_accuracy(review_app, lesson):
    original = deepcopy(lesson.content)
    proof = _confirmed(lesson)['review_token']
    result = review_submission(lesson, 7, _project(lesson),
                               [PARAPHRASE, lesson.content['items'][1]['english']], [proof, None])
    assert result['success'] is True
    assert result['completed'] is True
    assert result['passed'] is True
    assert result['score'] is None
    assert result['assessment'] == 'self_review'
    assert result['correct_items'] == 1
    assert result['reviewed_items'] == [0]
    assert result['total_items'] == 2
    assert result['item_results'][0]['correct'] is None
    assert lesson.content == original


def test_final_proof_cannot_survive_answer_change_or_raw_item_edit(review_app, lesson):
    token = _confirmed(lesson)['review_token']
    answers = ['The team verified the documents for half a year.', lesson.content['items'][1]['english']]
    assert review_submission(lesson, 7, _project(lesson), answers, [token, None])['success'] is False
    lesson.content['items'][0]['hint_words'] = ['Changed raw item field']
    answers[0] = PARAPHRASE
    assert review_submission(lesson, 7, _project(lesson), answers, [token, None])['success'] is False


def test_reviewed_proof_also_expires(review_app, lesson):
    with patch.object(TimestampSigner, 'get_timestamp', return_value=100_000):
        token = _confirmed(lesson)['review_token']
    with patch.object(TimestampSigner, 'get_timestamp', return_value=103_601):
        result = review_submission(lesson, 7, _project(lesson),
                                   [PARAPHRASE, lesson.content['items'][1]['english']], [token, None])
    assert result['error'] == 'invalid_review_token'


def test_projected_items_must_keep_source_index_identity(review_app, lesson):
    items = list(reversed(_project(lesson)))
    result = review_submission(lesson, 7, items, [CANONICAL, 'Both sides negotiated.'], [])
    assert result['success'] is False
    assert result['error'] == 'invalid_item'


def test_approved_registry_variants_use_same_automatic_match(review_app, lesson, monkeypatch):
    from app.curriculum import translation_variants

    monkeypatch.setattr(translation_variants, 'get_translation_variants',
                        lambda _english, _russian: (PARAPHRASE,))
    assert review_item(lesson, 7, 0, PARAPHRASE)['status'] == 'matched'


def test_corrected_projection_aligns_while_token_keeps_original_raw_item(review_app, lesson, monkeypatch):
    from app.curriculum import translation_variants

    def corrected_reference(english, russian):
        if english == CANONICAL:
            return 'A corrected canonical reference sentence.', 'Исправленный русский эталон.'
        return english, russian

    monkeypatch.setattr(translation_variants, 'translation_reference', corrected_reference)
    monkeypatch.setattr(translation_variants, 'get_translation_variants', lambda _english, _russian: ())
    proof = _confirmed(lesson)['review_token']
    items = _project(lesson)
    items[0]['english'], items[0]['russian'] = corrected_reference(items[0]['english'], items[0]['russian'])
    result = review_submission(lesson, 7, items,
                               [PARAPHRASE, lesson.content['items'][1]['english']], [proof, None])
    assert result['completed'] is True
    assert lesson.content['items'][0]['english'] == CANONICAL
    assert result['item_results'][0]['reference_answer'] == 'A corrected canonical reference sentence.'


def test_registry_change_invalidates_old_review_even_if_raw_source_unchanged(review_app, lesson, monkeypatch):
    from app.curriculum import translation_variants

    token = _confirmed(lesson)['review_token']
    monkeypatch.setattr(translation_variants, 'get_translation_variants',
                        lambda _english, _russian: ('An additional approved reference sentence.',))
    result = review_submission(lesson, 7, _project(lesson),
                               [PARAPHRASE, lesson.content['items'][1]['english']], [token, None])
    assert result['error'] == 'invalid_review_token'
