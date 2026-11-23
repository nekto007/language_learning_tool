"""The route never unlocks work or mistakes activity coverage for mastery."""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from app.daily_plan.learning_journey import project_journey
from app.daily_plan.plan_builder import build_required_snapshot


def module(level='A1'):
    return NS(id=7, number=3, title='Synthetic module', description='A practical goal',
              level=NS(code=level), raw_content={})


def lesson(number, kind, owner=None):
    return NS(id=number, number=number, title=f'Step {number}', type=kind, module=owner or module())


def item(number, **flags):
    return {'id': f'curriculum:{number}', 'kind': 'curriculum', 'data': {'lesson_id': number},
            'url': f'/lesson/{number}', **flags}


def test_only_current_plan_step_has_a_link_and_all_four_skills_remain_visible():
    lessons = [lesson(1, 'vocabulary'), lesson(2, 'reading'), lesson(3, 'writing_prompt')]
    result = project_journey(module(), lessons, set(), [item(1), item(2)], [item(3)])
    assert [x['state'] for x in result['nodes']] == ['current', 'locked', 'locked']
    assert [x['url'] for x in result['nodes']] == ['/lesson/1', None, None]
    assert {x['id']: x['total'] for x in result['skills']} == {
        'reading': 1, 'listening': 0, 'speaking': 0, 'writing': 1,
    }
    assert all(x['completed'] == 0 for x in result['skills'])


def test_independent_review_stays_before_next_course_node_and_skipped_is_not_completed():
    required = [item(1, skipped=True), {'id': 'srs:global', 'kind': 'srs'}, item(2, blocked=True)]
    result = project_journey(module(), [lesson(1, 'reading'), lesson(2, 'reading')], set(), required, [])
    assert all(x['state'] == 'locked' and x['item_id'] is None for x in result['nodes'])
    assert result['completed'] == 0


def test_completing_required_unlocks_only_first_optional_and_counts_real_activity():
    result = project_journey(module(), [lesson(1, 'dictation'), lesson(2, 'reading'), lesson(3, 'pronunciation')],
                             {1}, [item(1, completed=True)], [item(2), item(3)])
    assert [x['state'] for x in result['nodes']] == ['completed', 'current', 'locked']
    assert {x['id']: x['completed'] for x in result['skills']} == {
        'reading': 0, 'listening': 1, 'speaking': 0, 'writing': 1,
    }


def test_correction_opens_its_own_attempt_and_keeps_next_course_node_locked():
    correction = item(1)
    correction['id'] = 'correction:uuid'
    correction['data']['quiz_phase'] = 'correction'
    result = project_journey(module(), [lesson(1, 'reading'), lesson(2, 'writing_prompt')],
                             {1}, [correction, item(2)], [])
    assert result['nodes'][0]['state'] == 'correction'
    assert result['nodes'][0]['item_id'] == 'correction:uuid'
    assert result['nodes'][1]['item_id'] is None
    assert result['completed'] == 0


def test_private_outcomes_and_legacy_wrapped_metadata_have_identical_projection():
    owner = module()
    owner.raw_content = {'module': {'learning_journey': {'goal': 'Synthetic authored outcome'}}}
    assert project_journey(owner, [], set(), [], [])['goal'] == 'Synthetic authored outcome'
    assert project_journey(module('A2'), [], set(), [], []) is None


@pytest.mark.parametrize('tier,count', [('calm', 1), ('normal', 2), ('intensive', 3)])
def test_new_a1_day_honours_pace_without_an_extra_reading_or_minimum_filler(tier, count):
    lessons = [lesson(n, 'reading' if n == 1 else 'quiz') for n in range(1, count + 1)]
    with patch('app.daily_plan.plan_builder._collect_curriculum_chain', return_value=lessons), \
         patch('app.daily_plan.plan_builder._curriculum_item_dict', side_effect=lambda _u, _db, step, **_: item(step.id)), \
         patch('app.daily_plan.plan_builder._srs_item_dict', return_value=None), \
         patch('app.daily_plan.plan_builder._reading_item_dict') as extra_reading, \
         patch('app.daily_plan.learning_journey.is_a1_learner', return_value=True), \
         patch('app.daily_plan.plan_builder._minimum_filler_item_dict') as filler:
        result = build_required_snapshot(1, tier, NS())
    assert [x['id'] for x in result] == [f'curriculum:{n}' for n in range(1, count + 1)]
    extra_reading.assert_not_called()
    filler.assert_not_called()


def test_route_templates_escape_authored_goals_and_dont_link_future_steps(app):
    journey = project_journey(module(), [lesson(1, 'reading'), lesson(2, 'writing_prompt')], set(), [item(1), item(2)], [])
    journey['goal'] = '<script>private</script>'
    with app.test_request_context('/'):
        output = app.jinja_env.get_template('components/_learning_journey.html').render(
            unified_plan={'learning_journey': journey, 'required': [item(1), item(2)]},
        )
    assert '<script>' not in output
    assert '&lt;script&gt;' in output
    assert 'href="/lesson/2"' not in output
    assert 'href="/lesson/1"' in output
