"""Tests for Telegram mission plan formatting."""
import pytest

from app.telegram.notifications import (
    format_mission_plan_text,
    format_mission_morning_reminder,
)


def _make_phase(phase: str, title: str, completed: bool = False,
                source_kind: str = 'normal_course', mode: str = 'practice') -> dict:
    return {
        'id': 'abc123',
        'phase': phase,
        'title': title,
        'source_kind': source_kind,
        'mode': mode,
        'required': True,
        'completed': completed,
    }


def _make_mission_plan(mission_type: str = 'progress',
                       title: str = 'Продвижение вперёд',
                       reason_text: str = 'Следующий шаг в курсе',
                       phases: list | None = None,
                       completion: dict | None = None) -> dict:
    if phases is None:
        phases = [
            _make_phase('recall', 'Вспомни слова'),
            _make_phase('learn', 'Новый урок'),
            _make_phase('use', 'Практика'),
        ]
    return {
        'plan_version': 'v1',
        'mission': {
            'type': mission_type,
            'title': title,
            'reason_code': f'{mission_type}_default',
            'reason_text': reason_text,
        },
        'primary_goal': {
            'type': 'complete_phases',
            'title': 'Пройти все фазы',
            'success_criterion': 'all_phases_done',
        },
        'primary_source': {
            'kind': 'normal_course',
            'id': '1',
            'label': 'English A2',
        },
        'phases': phases,
        'completion': completion,
    }


class TestFormatMissionPlanText:
    def test_progress_mission_basic(self):
        plan = _make_mission_plan()
        text = format_mission_plan_text(plan)

        assert '\U0001f680' in text  # rocket emoji for progress
        assert 'Продвижение вперёд' in text
        assert '0/3' in text
        assert 'Следующий шаг в курсе' in text
        assert 'Вспомни слова' in text
        assert 'Новый урок' in text
        assert 'Практика' in text

    def test_repair_mission_basic(self):
        phases = [
            _make_phase('recall', 'Повтори слова SRS', source_kind='srs'),
            _make_phase('learn', 'Слабая грамматика', source_kind='grammar_lab'),
            _make_phase('use', 'Тренировка', source_kind='grammar_lab'),
            _make_phase('close', 'Завершение'),
        ]
        plan = _make_mission_plan(
            mission_type='repair',
            title='Закрепление материала',
            reason_text='Накопились слова для повтора',
            phases=phases,
        )
        text = format_mission_plan_text(plan)

        assert '\U0001f527' in text  # wrench emoji for repair
        assert 'Закрепление материала' in text
        assert '0/4' in text
        assert 'Повтори слова SRS' in text
        assert 'Завершение' in text

    def test_reading_mission_basic(self):
        phases = [
            _make_phase('recall', 'Вспомни лексику', source_kind='vocab'),
            _make_phase('read', 'Читай главу', source_kind='books'),
            _make_phase('use', 'Используй слова', source_kind='vocab'),
        ]
        plan = _make_mission_plan(
            mission_type='reading',
            title='Чтение книги',
            reason_text='Продолжай чтение',
            phases=phases,
        )
        text = format_mission_plan_text(plan)

        assert '\U0001f4d6' in text  # book emoji for reading
        assert 'Чтение книги' in text
        assert 'Читай главу' in text

    def test_phase_status_emoji_all_pending(self):
        plan = _make_mission_plan()
        text = format_mission_plan_text(plan)

        lines = text.split('\n')
        phase_lines = [l for l in lines if l.startswith(('\u25b6', '\u2b1c', '\u2705'))]
        assert len(phase_lines) == 3
        assert phase_lines[0].startswith('\u25b6\ufe0f')  # first = active
        assert phase_lines[1].startswith('\u2b1c')  # second = pending
        assert phase_lines[2].startswith('\u2b1c')  # third = pending

    def test_phase_status_emoji_first_done(self):
        phases = [
            _make_phase('recall', 'Вспомни слова', completed=True),
            _make_phase('learn', 'Новый урок'),
            _make_phase('use', 'Практика'),
        ]
        plan = _make_mission_plan(phases=phases)
        text = format_mission_plan_text(plan)

        lines = text.split('\n')
        phase_lines = [l for l in lines if l.startswith(('\u25b6', '\u2b1c', '\u2705'))]
        assert phase_lines[0].startswith('\u2705')  # done
        assert phase_lines[1].startswith('\u25b6\ufe0f')  # now active
        assert phase_lines[2].startswith('\u2b1c')  # pending

    def test_all_phases_completed_shows_completion_message(self):
        phases = [
            _make_phase('recall', 'Вспомни слова', completed=True),
            _make_phase('learn', 'Новый урок', completed=True),
            _make_phase('use', 'Практика', completed=True),
        ]
        plan = _make_mission_plan(phases=phases)
        text = format_mission_plan_text(plan)

        assert '3/3' in text
        assert 'Миссия выполнена' in text

    def test_all_phases_completed_custom_message(self):
        phases = [
            _make_phase('recall', 'A', completed=True),
            _make_phase('learn', 'B', completed=True),
            _make_phase('use', 'C', completed=True),
        ]
        plan = _make_mission_plan(
            phases=phases,
            completion={'message': 'Супер! Всё готово!'},
        )
        text = format_mission_plan_text(plan)

        assert 'Супер! Всё готово!' in text

    def test_no_reason_text(self):
        plan = _make_mission_plan(reason_text='')
        text = format_mission_plan_text(plan)
        lines = text.split('\n')
        assert lines[1] == ''
        assert not lines[2] == ''

    def test_empty_phases(self):
        plan = _make_mission_plan(phases=[])
        plan['phases'] = []
        text = format_mission_plan_text(plan)
        assert '0/0' in text

    def test_numbered_phases(self):
        plan = _make_mission_plan()
        text = format_mission_plan_text(plan)
        assert '1.' in text
        assert '2.' in text
        assert '3.' in text

    def test_phase_emoji_types(self):
        phases = [
            _make_phase('recall', 'Recall'),
            _make_phase('learn', 'Learn'),
            _make_phase('use', 'Use'),
            _make_phase('check', 'Check'),
        ]
        plan = _make_mission_plan(phases=phases)
        text = format_mission_plan_text(plan)

        assert '\U0001f9e0' in text  # recall = brain
        assert '\U0001f4da' in text  # learn = books
        assert '\u270d\ufe0f' in text  # use = writing hand
        assert '\u2705' in text  # check = checkmark (status or phase emoji)


class TestFormatMissionMorningReminder:
    def test_basic_morning_reminder(self):
        plan = _make_mission_plan()
        text, reply_markup = format_mission_morning_reminder(
            'Игорь', 5, plan, 'https://example.com')

        assert 'Доброе утро, Игорь' in text
        assert '5 дней подряд' in text
        assert 'Продвижение вперёд' in text
        assert reply_markup is not None
        assert len(reply_markup['inline_keyboard']) == 1
        assert 'example.com/study' in reply_markup['inline_keyboard'][0][0]['url']

    def test_zero_streak(self):
        plan = _make_mission_plan()
        text, _ = format_mission_morning_reminder('Игорь', 0, plan, 'https://example.com')

        assert 'Доброе утро, Игорь' in text
        assert 'дней подряд' not in text

    def test_no_site_url(self):
        plan = _make_mission_plan()
        _, reply_markup = format_mission_morning_reminder('Игорь', 5, plan, '')

        assert reply_markup is None

    def test_all_three_mission_types(self):
        for mission_type in ['progress', 'repair', 'reading']:
            plan = _make_mission_plan(mission_type=mission_type, title=f'Mission {mission_type}')
            text, _ = format_mission_morning_reminder('User', 1, plan, 'https://x.com')
            assert f'Mission {mission_type}' in text


class TestLegacyFormatUnchanged:
    """Verify that legacy plan (without mission key) is not affected."""

    def test_format_mission_plan_text_handles_legacy_gracefully(self):
        legacy_plan = {
            'next_lesson': {'lesson_id': 1, 'title': 'Test', 'module_number': 1},
            'grammar_topic': None,
            'words_due': 5,
        }
        assert 'mission' not in legacy_plan
        text = format_mission_plan_text(legacy_plan)
        assert 'План на сегодня' in text
        assert '0/0' in text
