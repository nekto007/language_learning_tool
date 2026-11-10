"""Standalone methodology editor checks; no Flask/DB or local corpus required."""
import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'complete_lesson_explanations', Path(__file__).resolve().parents[2] /
    'scripts/complete_lesson_explanations.py')
editor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(editor)


class MethodologyExplanationTests(unittest.TestCase):
    def test_empty_quiz_explanation_has_actual_rule(self):
        note = editor.propose_explanation(
            {'level': 'A1', 'order': 1, 'lessons': []}, {'type': 'translation_quiz'},
            {'correct': 'I am a teacher.'})
        self.assertIn('согласуется', note)
        self.assertNotIn('Правильный ответ:', note)

    def test_had_money_is_not_past_perfect(self):
        note = editor.grammar_note('If I had money, I would travel.', {'level': 'B2', 'order': 5})
        self.assertIn('Past Simple', note)
        self.assertNotIn('смешанное', note)

    def test_had_known_with_would_have_is_third_conditional(self):
        note = editor.grammar_note("If I had known, I wouldn't have left.", {'level': 'C1', 'order': 7})
        self.assertIn('Third Conditional', note)

    def test_embedded_if_does_not_receive_conditional_rule(self):
        note = editor.grammar_note("I'm not sure if therapy would help me.", {'level': 'B2', 'order': 6})
        self.assertIn('косвенного вопроса', note)
        self.assertNotIn('if + Past Simple', note)

    def test_going_to_is_not_mislabelled_current_process(self):
        note = editor.grammar_note('I am going to visit Rome.', {'level': 'A2', 'order': 17})
        self.assertIn('намерение', note)

    def test_future_continuous_contractions_are_recognized(self):
        note = editor.grammar_note("I'll be working tomorrow.", {'level': 'C1', 'order': 1})
        self.assertIn('Will be + V-ing', note)

    def test_invalid_boolean_transcript_is_not_explained_as_comprehension(self):
        note = editor.propose_explanation({'level': 'A1', 'order': 14, 'lessons': []},
                                         {'type': 'listening_quiz'},
                                         {'correct': 'True', 'audio_text': 'True',
                                          'question': 'She can dance very well.'})
        self.assertEqual(note, '')

    def test_can_does_not_match_inside_cant(self):
        module = {'lessons': [{'type': 'vocabulary', 'content': {'vocabulary': [
            {'english': 'can', 'russian': 'мочь'}, {'english': "can't", 'russian': 'не мочь'},
        ]}}]}
        note = editor.lexical_notes(module, "She can't draw.")
        self.assertIn("«can't»", note)
        self.assertNotIn('«can»', note)

    def test_existing_explanation_and_translation_lesson_are_preserved(self):
        module = {'level': 'A1', 'order': 1, 'lessons': [
            {'type': 'translation', 'content': {'external_key': 'translation',
                                               'items': [{'english': 'hello', 'alternatives': ['hi']}]}},
            {'id': 42, 'type': 'translation_quiz', 'content': {'external_key': 'quiz', 'audio': 'same.mp3',
                'exercises': [{'correct': 'I am a teacher.', 'explanation': 'Existing authored explanation.'},
                              {'correct': 'I am happy.', 'explanation': ''}]}},
        ]}
        before = deepcopy(module)
        counts, proposals, unresolved = editor.process_module(module, apply=True)
        self.assertEqual(module['lessons'][0], before['lessons'][0])
        self.assertEqual(module['lessons'][1]['id'], 42)
        self.assertEqual(module['lessons'][1]['content']['audio'], 'same.mp3')
        self.assertEqual(module['lessons'][1]['content']['exercises'][0],
                         before['lessons'][1]['content']['exercises'][0])
        self.assertEqual(counts['translation_quiz_missing'], 1)
        self.assertEqual(set(proposals['quiz']), {'1'})
        self.assertEqual(unresolved, [])

    def test_known_wrong_question_answer_is_repaired(self):
        task = {'question': 'Преобразуйте утверждение в вопрос: Local culture shapes the way people celebrate important events.',
                'correct': 'Local culture shapes the way people celebrate important events.'}
        module = {'level': 'B2', 'order': 4, 'lessons': [
            {'type': 'final_test', 'content': {'test_sections': [{'exercises': [task]}]}}]}
        self.assertEqual(editor.repair_known_question(module), 1)
        self.assertEqual(task['correct'], 'Does local culture shape the way people celebrate important events?')
        self.assertEqual(task['acceptable_answers'], [task['correct']])
        self.assertEqual(editor.repair_known_question(module), 0)

    def test_warmup_label_does_not_change_audio_or_exercise(self):
        lesson = {'type': 'listening_quiz', 'title': 'Аудирование: Ecology',
                  'content': {'external_key': 'same', 'exercises': [
                      {'correct': 'emission', 'audio_text': 'emission', 'audio': 'same.mp3'}]}}
        original = deepcopy(lesson['content'])
        module = {'level': 'B2', 'order': 13, 'lessons': [lesson]}
        self.assertEqual(editor.label_advanced_warmup(module), 1)
        self.assertEqual(lesson['content'], original)
        self.assertEqual(editor.label_advanced_warmup(module), 0)


if __name__ == '__main__':
    unittest.main()
