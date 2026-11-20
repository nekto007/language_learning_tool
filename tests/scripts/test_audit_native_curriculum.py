"""Whole-corpus audit classifies real schemas, not every lesson as an exam."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import audit_native_curriculum as audit


def write_module(tmp_path, lessons):
    source = tmp_path / 'source'
    source.mkdir(exist_ok=True)
    path = source / 'module_A1_1_fixture.json'
    path.write_text(json.dumps({'module': {'id': 1, 'order': 1, 'level': 'A1', 'lessons': [
        {'id': index, 'order': index, 'type': kind, 'title': kind, 'content': deepcopy(content)}
        for index, (kind, content) in enumerate(lessons, 1)
    ]}}, ensure_ascii=False), encoding='utf-8')
    return source, path


def actual_shapes():
    return [
        ('vocabulary', {'vocabulary': [{'english': 'bag', 'russian': 'сумка'}]}),
        ('flashcards', {'cards': [{'front': 'bag', 'back': 'сумка'}]}),
        ('grammar', {'rule': 'I am; she is.', 'exercises': []}),
        ('dialogue_completion_quiz', {'exercises': [{
            'type': 'dialogue_completion', 'dialogue': [
                {'speaker': 'A', 'text': 'Have you got a leash?'},
                {'speaker': 'B', 'text': '___', 'blank': True},
            ], 'options': ["Yes, I've got a leash.", 'Yes, I has a leash.'],
            'correct': "Yes, I've got a leash.",
        }]}),
        ('sentence_completion', {'items': [{
            'mode': 'transformation', 'context': 'Переформулируй «We finished the tour», используя having.',
            'prompt': '', 'answer': 'Having finished', 'prompt_after': 'the tour, we rested.',
            'hint': 'H••••• f•••••••',
        }]}),
        ('translation', {'mode': 'guided', 'items': [{
            'russian': 'Положи сумку на стол.', 'english': 'Put the bag on the table.',
            'hint_words': ['Put', 'the', 'bag', 'on', 'the', 'table.'],
        }]}),
        ('listening_immersion', {'audio_url': '/static/audio/example.mp3',
                                 'text': 'I have two blue bags in the room.',
                                 'comprehension_questions': [{'type': 'multiple_choice', 'question': 'How many bags?',
                                                              'options': ['one', 'two'], 'correct': 'two'}]}),
        ('shadow_reading', {'audio_url': '/static/audio/shadow.mp3', 'text': 'I have a blue bag.'}),
        ('writing_prompt', {'prompt': 'Describe your bag.', 'checklist': ['Цвет', 'Размер', 'Детали'],
                            'min_sentences': 2, 'min_words': 0, 'min_checklist': 2}),
        ('final_test', {'test_sections': [{'title': 'Реальные regression cases', 'exercises': [
            {'type': 'ordering', 'words': ['I', 'wake', 'up', 'early'], 'correct': 'I wake up early.'},
            {'type': 'fill_blank', 'question': 'She has collected bags since ___.',
             'options': ['2018', 'five years', 'recently'], 'correct': '2018'},
        ]}]}),
    ]


def test_actual_dialogue_suffix_hint_wordbank_and_nonobjective_schemas_pass_without_writes(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, 'create_app', lambda *a, **kw: pytest.fail('Audit must not start Flask'))
    source, path = write_module(tmp_path, actual_shapes())
    before = path.read_bytes()
    lessons = audit.load_lessons(source)
    projection = audit.projection_audit(lessons)
    grading = audit.grading_audit(lessons)
    assert projection['passed'] and projection['issues'] == {}
    assert projection['projection_status_counts'] == {'dedicated_cards_route': 2, 'projected': 8}
    assert projection['informational_counts'] == {'listening_comprehension_transcript_intentionally_hidden': 1}
    assert grading['passed'] and grading['failure_count'] == 0
    assert grading['skip_counts'] == {'dedicated_cards': 2, 'theory_only': 1, 'self_assessed': 1, 'writing': 1}
    listening = next(record for record in grading['records'] if record['type'] == 'listening_immersion')
    assert listening['post_answer_transcript_available'] is False
    assert path.read_bytes() == before
    assert projection['database_access'] is grading['database_access'] is False


def test_hidden_reference_is_informational_only_for_actual_objective_listening(tmp_path, monkeypatch):
    listening = actual_shapes()[6]
    source, _ = write_module(tmp_path, [listening])
    lessons = audit.load_lessons(source)
    original_extras = audit.extras

    def false_self_assessment(proxy):
        result = original_extras(proxy)
        result['assessment'] = 'self_assessed'
        return result

    monkeypatch.setattr(audit, 'extras', false_self_assessment)
    result = audit.projection_audit(lessons)
    assert result['passed'] is False
    assert result['issue_counts']['self_assessed_listening_text_lost'] == 1
    assert not result['informational_counts']


def test_missing_reference_in_confirmation_listening_is_a_real_failure(tmp_path, monkeypatch):
    source, _ = write_module(tmp_path, [('listening_immersion', {
        'audio_url': '/static/audio/example.mp3', 'text': 'Study and repeat this sentence.',
    })])
    original = audit.extras

    def missing_text(proxy):
        result = original(proxy)
        result['theory'] = []
        return result

    monkeypatch.setattr(audit, 'extras', missing_text)
    result = audit.projection_audit(audit.load_lessons(source))
    assert result['issue_counts']['self_assessed_listening_text_lost'] == 1
    assert not result['informational_counts']


def test_audit_detects_regressed_suffix_hint_and_duplicate_wordbank_loss(tmp_path, monkeypatch):
    shapes = actual_shapes()
    source, _ = write_module(tmp_path, [shapes[4], shapes[5]])
    original = audit.project_questions

    def broken_projection(proxy):
        questions = original(proxy)
        if proxy.type == 'sentence_completion':
            questions[0]['prompt'] = '___'
            questions[0]['instruction'] = 'Введи ответ'
        else:
            prefix, bank = questions[0]['instruction'].split('Слова для перевода: ')
            tokens = bank.split(' · ')
            tokens.remove('the')
            questions[0]['instruction'] = prefix + 'Слова для перевода: ' + ' · '.join(tokens)
        return questions

    monkeypatch.setattr(audit, 'project_questions', broken_projection)
    result = audit.projection_audit(audit.load_lessons(source))
    assert result['issue_counts']['sentence_completion_prompt_after_lost'] == 1
    assert result['issue_counts']['sentence_completion_hint_lost'] == 1
    assert result['issue_counts']['guided_translation_wordbank_lost'] == 1


def test_audio_transcript_leak_and_missing_audio_remain_failures(tmp_path, monkeypatch):
    text = 'She has got two ID cards.'
    source, _ = write_module(tmp_path, [('listening_quiz', {'exercises': [{
        'type': 'listening_choice', 'audio': '[sound:cards.mp3]', 'text': text, 'transcript': text,
        'question': 'How many cards?', 'options': ['one', 'two'], 'correct': 'two',
    }]})])
    original = audit.project_questions

    def leak(proxy):
        questions = original(proxy)
        questions[0]['prompt'] += '\n' + text
        questions[0]['audio_url'] = None
        return questions

    monkeypatch.setattr(audit, 'project_questions', leak)
    result = audit.projection_audit(audit.load_lessons(source))
    assert result['issue_counts']['listening_transcript_leaked_in_prompt'] == 1
    assert result['issue_counts']['required_question_audio_lost'] == 1


def test_cli_writes_both_reports_and_fails_empty_source(tmp_path):
    source, path = write_module(tmp_path, actual_shapes())
    before = path.read_bytes()
    projection, grading = tmp_path / 'projection.json', tmp_path / 'grading.json'
    assert audit.main(['--source', str(source), '--output', str(projection), '--grade-output', str(grading)]) == 0
    assert json.loads(projection.read_text())['passed'] is True
    assert json.loads(grading.read_text())['passed'] is True
    assert path.read_bytes() == before
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert audit.main(['--source', str(empty)]) == 2


def test_audit_checks_all_visible_options_not_only_the_canonical_one(tmp_path, monkeypatch):
    source, _ = write_module(tmp_path, [actual_shapes()[3]])
    original = audit.project_questions

    def missing_wrong_option(proxy):
        questions = original(proxy)
        questions[0]['options'] = [option for option in questions[0]['options'] if option['value'] == '0']
        return questions

    monkeypatch.setattr(audit, 'project_questions', missing_wrong_option)
    result = audit.projection_audit(audit.load_lessons(source))
    assert result['issue_counts']['answer_input_options_lost'] == 1


def test_canonical_helper_distinguishes_numeric_option_labels_from_explicit_indexes():
    q = {'input': 'choice'}
    assert audit._widget_answer({'type': 'multiple_choice', 'options': ['2018', 'other'], 'correct': '2018'}, q) == '0'
    assert audit._widget_answer({'type': 'multiple_choice', 'options': ['1', '0'], 'correct': '0'}, q) == '1'
    assert audit._widget_answer({'type': 'multiple_choice', 'options': ['1', '0'], 'correct_index': 0}, q) == '0'
    with pytest.raises(ValueError, match='boolean'):
        audit._widget_answer({'type': 'true_false', 'correct': 'unknown'}, q)


def test_report_paths_cannot_overwrite_or_pollute_authored_sources(tmp_path):
    source, path = write_module(tmp_path, actual_shapes())
    before = path.read_bytes()
    assert audit.main(['--source', str(source), '--output', str(path)]) == 2
    assert audit.main(['--source', str(path), '--grade-output', str(path)]) == 2
    assert audit.main(['--source', str(source), '--output', str(source / 'report.json')]) == 2
    assert path.read_bytes() == before
