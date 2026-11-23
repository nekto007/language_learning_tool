"""Draft input cannot replace correction, receipt, score or scheduling ledgers."""
from copy import deepcopy

import pytest

from app.curriculum.progress_drafts import merge_client_draft


@pytest.mark.parametrize('field', [
    'quiz_correction', '_native_submission', '_native_card_submissions', '_native_receipts',
    '_native_legacy_draft', '_native_legacy_draft_origin',
    'native_card_rounds', 'native_cards_session', 'score', 'last_score', 'best_score',
    'passed', 'completed', 'status', 'completed_at', 'completion', 'completion_state',
    'feedback', 'item_results', 'correct_words', 'total_words', 'correct_items', 'total_items',
    'failed_by_attempt_limit', 'studied_cards', 'cards_studied', 'accuracy', 'dictation_attempts', 'card_progress',
])
def test_reserved_fields_are_rejected_before_mutating_existing_state(field):
    server = {'quiz_correction': {'status': 'pending', 'first_score': 50},
              '_native_submission': {'nonce': 'committed-receipt', 'response': {'score': 50}}}
    before = deepcopy(server)
    with pytest.raises(ValueError, match='invalid_draft_fields'):
        merge_client_draft(server, {'answers': {'0': 'my answer'}, field: {'score': 100}})
    assert server == before


def test_normal_editor_inputs_keep_committed_state_and_do_not_alias_it():
    server = {'quiz_correction': {'status': 'completed', 'first_score': 50,
                                  'first_answers': {'0': 'first independent answer'}},
              '_native_submission': {'nonce': 'saved', 'response': {'score': 50}},
              'native_card_rounds': {'revision': 'server-revision', 'ratings': {'card:1': 3}},
              'native_cards_session': 17, 'score': 50, 'passed': True}
    draft = {'answers': {'0': 'my new input'}, 'current_question': 1,
             'items': [{'value': 'is', 'status': 'correct', 'attempts': 2}],
             'reading_answers': {'q1': 'b'}, 'card_index': 2, 'presented': [0, 1, 2],
             'flipped': [0, 1], 'total_cards': 6, 'theory_studied': True,
             'correct_answers': 1, 'total_questions': 2}
    before = deepcopy(server)
    merged = merge_client_draft(server, draft)
    for key, value in server.items():
        assert merged[key] == value
    for key, value in draft.items():
        assert merged[key] == value
    merged['quiz_correction']['first_answers']['0'] = 'changed copy'
    merged['answers']['0'] = 'changed draft copy'
    assert server == before and draft['answers']['0'] == 'my new input'


def test_non_dict_or_non_string_root_keys_are_rejected():
    for draft in (None, [], 'input', {1: 'value'}):
        with pytest.raises(ValueError, match='invalid_draft_fields'):
            merge_client_draft({}, draft)


@pytest.mark.parametrize('saved', [None, [], False, 42, {'0': {'correct_answer': 'private'}},
                                   {'0': True}, [None, False, {'pairs': 'invalid'}]])
def test_archive_does_not_invent_input_from_malformed_snapshots(saved: object) -> None:
    from types import SimpleNamespace
    from app.curriculum.progress_drafts import legacy_final_input_archive

    assert legacy_final_input_archive(SimpleNamespace(data={'answers': saved})) is None


def test_existing_archive_keeps_only_owned_input_and_does_not_alias_saved_state() -> None:
    from types import SimpleNamespace
    from app.curriculum.progress_drafts import legacy_final_input_archive

    data = {'_native_legacy_draft': {'answers': {'0': {
        'value': 'own answer', 'correct': True, 'correct_answer': 'private',
        'pairs': [{'left': 'own left', 'right': 'own right', 'correct': False}]}},
        'feedback': 'private'}, '_native_submission': {'nonce': 'later-attempt'}}
    before = deepcopy(data)
    copied = legacy_final_input_archive(SimpleNamespace(data=data))
    assert copied == {'answers': {'0': {'value': 'own answer',
                                       'pairs': [{'left': 'own left', 'right': 'own right'}]}}}
    copied['answers']['0']['pairs'][0]['right'] = 'different copy'
    assert data == before
