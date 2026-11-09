"""Pure selector tests; no Flask app or database is required."""
import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'action_selection', Path(__file__).resolve().parents[2] / 'app/daily_plan/action_selection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def item(key, **changes):
    return {'id': key, 'url': f'/learn/{key}/', **changes}


class NextUnifiedItemTests(unittest.TestCase):
    def test_required_order_precedes_optional(self):
        first, second, optional = item('1'), item('2'), item('3')
        plan = {'mode': 'unified', 'required': [first, second], 'optional': [optional]}
        self.assertIs(selection.next_unified_item(plan, {}), first)
        self.assertIs(selection.next_unified_item(plan, {'1': True}), second)

    def test_summary_done_and_all_nonactionable_states_are_skipped(self):
        expected = item('6')
        plan = {'required': [item('1'), item('2', completed=True), item('3', skipped=True),
                             item('4', blocked=True), item('5', url=None), expected]}
        self.assertIs(selection.next_unified_item(plan, {'1': True}), expected)

    def test_empty_url_is_skipped(self):
        expected = item('2')
        self.assertIs(selection.next_unified_item({'required': [item('1', url=''), expected]}, {}), expected)

    def test_optional_keeps_existing_api_semantics_after_skipped_required(self):
        optional = item('2')
        plan = {'required': [item('1', skipped=True)], 'optional': [optional]}
        self.assertIs(selection.next_unified_item(plan, {}), optional)

    def test_resume_url_and_identity_are_preserved(self):
        expected = item('12', url='/learn/12/?source=linear_plan_card&from=linear_plan&slot=curriculum&x=a%2Bb')
        result = selection.next_unified_item({'required': [expected]}, {})
        self.assertIs(result, expected)
        self.assertEqual(result['url'], expected['url'])

    def test_inputs_are_not_mutated(self):
        plan = {'mode': 'unified', 'required': [item('1', skipped=True), item('2')],
                'optional': [item('3')], '_plan_meta': {'effective_mode': 'unified'}}
        completion = {'1': True}
        original_plan, original_completion = deepcopy(plan), deepcopy(completion)
        selection.next_unified_item(plan, completion)
        self.assertEqual(plan, original_plan)
        self.assertEqual(completion, original_completion)

    def test_pause_mode_rejects_stale_items(self):
        self.assertIsNone(selection.next_unified_item({'mode': 'paused', 'required': [item('1')]}, {}))

    def test_pause_metadata_rejects_stale_items(self):
        self.assertIsNone(selection.next_unified_item({
            'mode': 'unified', '_plan_meta': {'effective_mode': 'paused'}, 'required': [item('1')]}, {}))

    def test_empty_and_exhausted_plans_return_none(self):
        for plan in ({}, {'required': None, 'optional': None},
                     {'required': [item('1', completed=True)], 'optional': [item('2', blocked=True)]}):
            with self.subTest(plan=plan):
                self.assertIsNone(selection.next_unified_item(plan, {}))

    def test_none_completion_map_is_supported(self):
        expected = item('1')
        self.assertIs(selection.next_unified_item({'required': [expected]}, None), expected)


if __name__ == '__main__':
    unittest.main()
