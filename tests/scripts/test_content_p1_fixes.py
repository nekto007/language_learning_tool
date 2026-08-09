"""Tests for the CNT-002 / CNT-008 / CNT-009 corpus fixes (audit 2026-08-08).

The corpus itself is gitignored, so these exercise the transforms directly on
representative payloads plus, where the corpus is present, assert the real files
are clean.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fix_borrowed_lesson_audio import (
    build_usage,
    clip_name,
    clip_owner,
    find_borrowed,
    is_shareable,
    module_identity,
    strip_named,
)
from scripts.fix_mail_merge_dialogues import broken_reasons, filter_exercises
from scripts.fix_reading_matching_exercises import expand_matching, fix_content

CORPUS = Path(__file__).resolve().parents[2] / 'module_completed' / 'fixed'


# ---------------------------------------------------------------------------
# CNT-002 — matching exercises in reading lessons
# ---------------------------------------------------------------------------

MATCHING = {
    'type': 'matching',
    'instruction': 'Соотнесите слова с переводом',
    'pairs': [
        {'english': 'can', 'russian': 'мочь, уметь'},
        {'english': 'swim', 'russian': 'плавать'},
        {'english': 'drive', 'russian': 'водить машину'},
    ],
    'question': '',
    'correct': False,
}


class TestMatchingExpansion:
    def test_one_question_per_pair(self):
        expanded = expand_matching(MATCHING)

        assert len(expanded) == len(MATCHING['pairs'])
        assert {e['type'] for e in expanded} == {'multiple_choice'}

    def test_each_question_names_its_word(self):
        expanded = expand_matching(MATCHING)

        assert expanded[0]['question'] == 'Что означает «can»?'
        assert expanded[1]['question'] == 'Что означает «swim»?'

    def test_correct_answer_is_the_translation(self):
        for exercise, pair in zip(expand_matching(MATCHING), MATCHING['pairs']):
            assert exercise['correct'] == pair['russian']
            assert exercise['correct_answer'] == pair['russian']

    def test_correct_answer_is_among_the_options(self):
        for exercise in expand_matching(MATCHING):
            assert exercise['correct'] in exercise['options']

    def test_options_are_distinct(self):
        for exercise in expand_matching(MATCHING):
            assert len(set(exercise['options'])) == len(exercise['options'])

    def test_answer_is_not_always_in_the_same_slot(self):
        positions = {
            e['options'].index(e['correct']) for e in expand_matching(MATCHING)
        }
        assert len(positions) > 1

    def test_no_literal_false_survives_as_the_answer(self):
        """The old payload put `False` into data-correct, making 'false' pass."""
        for exercise in expand_matching(MATCHING):
            assert exercise['correct'] is not False

    def test_deterministic(self):
        assert expand_matching(MATCHING) == expand_matching(MATCHING)

    def test_other_types_pass_through(self):
        item = {'type': 'true_false', 'question': 'x', 'correct': True}
        assert expand_matching(item) == [item]

    def test_degenerate_pairs_are_left_for_a_human(self):
        item = {'type': 'matching', 'pairs': [{'english': 'a', 'russian': 'б'}]}
        assert expand_matching(item) == [item]

    def test_alternative_pair_shapes_are_read(self):
        item = {
            'type': 'matching',
            'pairs': [
                {'left': 'cat', 'right': 'кот'},
                {'word': 'dog', 'translation': 'пёс'},
            ],
        }
        expanded = expand_matching(item)

        assert expanded[0]['question'] == 'Что означает «cat»?'
        assert expanded[1]['correct'] == 'пёс'

    def test_fix_content_reports_and_replaces(self):
        content = {'exercises': [{'type': 'true_false'}, dict(MATCHING)]}
        new_content, count = fix_content(content)

        assert count == 1
        assert len(new_content['exercises']) == 1 + len(MATCHING['pairs'])

    def test_fix_content_is_idempotent(self):
        once, _ = fix_content({'exercises': [dict(MATCHING)]})
        twice, count = fix_content(once)

        assert count == 0
        assert twice == once


# ---------------------------------------------------------------------------
# CNT-008 — clips borrowed from another module
# ---------------------------------------------------------------------------

class TestBorrowedAudio:
    def test_prefix_identifies_the_owning_module(self):
        assert clip_owner('[sound:A2M22L6_ex1.mp3]') == ('A2', 22)
        assert clip_owner('/static/audio/A2M07L8_listen_1.mp3') == ('A2', 7)

    def test_pronunciation_clips_are_shareable(self):
        assert is_shareable('pronunciation_en_apple.mp3') is True
        assert is_shareable('[sound:A2M22L6_ex1.mp3]') is False

    def test_module_identity_from_filename(self):
        assert module_identity('module_A2_7_healthy_lifestyle.json') == ('A2', 7)

    def test_owner_wins_and_borrower_is_stripped(self):
        modules = {
            ('A2', 22): {'lessons': [{'content': {'items': [{'audio': '[sound:A2M22L6_ex1.mp3]'}]}}]},
            ('A2', 7): {'lessons': [{'content': {'items': [{'audio': '[sound:A2M22L6_ex1.mp3]'}]}}]},
        }
        owners = find_borrowed(build_usage(modules))

        assert owners == {'A2M22L6_ex1.mp3': ('A2', 22)}

    def test_single_module_use_is_never_borrowed(self):
        modules = {
            ('A2', 22): {'lessons': [{'content': {'items': [{'audio': '[sound:A2M22L6_ex1.mp3]'}]}}]},
        }
        assert find_borrowed(build_usage(modules)) == {}

    def test_shared_clip_with_no_matching_owner_is_left_alone(self):
        """Legacy numbering — guessing here would strip hundreds of good refs."""
        modules = {
            ('C1', 9): {'lessons': [{'content': {'items': [{'audio': '[sound:C1M3L6_line_1.mp3]'}]}}]},
            ('C1', 8): {'lessons': [{'content': {'items': [{'audio': '[sound:C1M3L6_line_1.mp3]'}]}}]},
        }
        assert find_borrowed(build_usage(modules)) == {}

    def test_strip_named_removes_the_key_for_string_refs(self):
        removed: list[str] = []
        result = strip_named(
            {'items': [{'audio': '[sound:A2M22L6_ex1.mp3]', 'question': 'q'}]},
            {'A2M22L6_ex1.mp3'}, removed,
        )

        assert result['items'][0] == {'question': 'q'}
        assert removed == ['[sound:A2M22L6_ex1.mp3]']

    def test_strip_named_keeps_list_alignment(self):
        removed: list[str] = []
        result = strip_named(
            {'audio': ['[sound:A2M22L6_ex1.mp3]', '[sound:A2M07L8_x.mp3]']},
            {'A2M22L6_ex1.mp3'}, removed,
        )

        assert result['audio'] == ['', '[sound:A2M07L8_x.mp3]']

    def test_clip_name_normalises_every_form(self):
        assert clip_name('[sound:a.mp3]') == 'a.mp3'
        assert clip_name('/static/audio/a.mp3') == 'a.mp3'


# ---------------------------------------------------------------------------
# CNT-009 — mail-merged dialogue exercises
# ---------------------------------------------------------------------------

class TestMailMergeDetection:
    @pytest.mark.parametrize('prompt,answer,reason', [
        (
            'A: Tell me about your tell — told. | B: ___',
            'My tell — told is special to me.',
            'verb_pair_echoed',
        ),
        (
            'A: What is your favorite keep — kept? | B: ___',
            'My favorite keep — kept is the new one.',
            'verb_pair_echoed',
        ),
        (
            'A: Do you have a brown? | B: ___',
            'Yes, I have a brown.',
            'adjective_echoed_without_head_noun',
        ),
    ])
    def test_broken_items_are_flagged(self, prompt, answer, reason):
        assert reason in broken_reasons({'dialogue': prompt, 'correct': answer})

    @pytest.mark.parametrize('prompt,answer', [
        # A dash separating clauses, not a verb pair in a noun slot.
        (
            'A: Suppose you found a wallet on the street — what would you do?',
            'I would take it to the police.',
        ),
        ('A: How was the maths exam?', 'It was a piece of cake — easier than I thought.'),
        ('A: How often do you go skiing?', 'Only once in a blue moon.'),
        # Adjective with a real head noun.
        ('A: What do you wear in winter?', 'I usually wear a warm coat.'),
        ('A: Is the sun shining today?', "Yes, it's a sunny day."),
        # Ordinary, well-formed items.
        ('A: Do you like lawyers?', 'Yes, I like lawyers.'),
        ('A: Where is the sofa?', 'The sofa is in the living room.'),
    ])
    def test_good_items_are_not_flagged(self, prompt, answer):
        assert broken_reasons({'dialogue': prompt, 'correct': answer}) == []

    def test_list_dialogue_shape_is_read(self):
        exercise = {
            'dialogue': [
                {'speaker': 'A', 'text': 'Do you have a brown?'},
                {'speaker': 'B', 'text': '___', 'blank': True},
            ],
            'correct': 'Yes, I have a brown.',
        }
        assert broken_reasons(exercise) == ['adjective_echoed_without_head_noun']

    def test_filter_drops_only_the_broken_one(self):
        good = {'dialogue': 'A: Do you like lawyers?', 'correct': 'Yes, I like lawyers.'}
        bad = {'dialogue': 'A: Do you have a brown?', 'correct': 'Yes, I have a brown.'}

        new_content, dropped = filter_exercises({'exercises': [good, bad]})

        assert new_content['exercises'] == [good]
        assert [d[0] for d in dropped] == [1]

    def test_filter_is_idempotent(self):
        content = {'exercises': [
            {'dialogue': 'A: Do you have a brown?', 'correct': 'Yes, I have a brown.'},
        ]}
        once, _ = filter_exercises(content)
        twice, dropped = filter_exercises(once)

        assert dropped == []
        assert twice == once


# ---------------------------------------------------------------------------
# Corpus-level assertions (skipped where the gitignored corpus is absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CORPUS.is_dir(), reason='module_completed/fixed not present')
class TestCorpusIsClean:
    @pytest.fixture(scope='class')
    def modules(self):
        return {
            path.name: json.loads(path.read_text(encoding='utf-8'))
            for path in sorted(CORPUS.glob('module_*.json'))
        }

    def test_no_reading_lesson_still_carries_a_matching_exercise(self, modules):
        offenders = []
        for name, data in modules.items():
            module = data.get('module') or data
            for lesson in module.get('lessons') or []:
                if lesson.get('type') != 'reading':
                    continue
                _new, count = fix_content(lesson.get('content') or {})
                if count:
                    offenders.append(f'{name} L{lesson.get("number")}')
        assert not offenders, offenders

    def test_no_lesson_clip_is_shared_across_modules(self, modules):
        by_identity = {}
        for name, data in modules.items():
            identity = module_identity(name)
            if identity:
                by_identity[identity] = data
        assert find_borrowed(build_usage(by_identity)) == {}

    def test_no_mail_merge_dialogue_survives(self, modules):
        offenders = []
        for name, data in modules.items():
            module = data.get('module') or data
            for lesson in module.get('lessons') or []:
                if lesson.get('type') != 'dialogue_completion_quiz':
                    continue
                _new, dropped = filter_exercises(lesson.get('content') or {})
                offenders.extend(f'{name} L{lesson.get("number")} ex[{d[0]}]' for d in dropped)
        assert not offenders, offenders
