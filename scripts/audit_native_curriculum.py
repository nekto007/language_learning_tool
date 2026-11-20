#!/usr/bin/env python3
"""Audit local curriculum display and objective native answer reachability.

Read-only: imports existing projectors/graders, never creates a Flask app, calls
an endpoint, opens a database session or uses the network. Card lessons use a
separate database-backed SRS route, so only their authored display shape is
checked. Writing, confirmation and open translation are not objective exams.

    python scripts/audit_native_curriculum.py --source module_completed/fixed \
        --output /tmp/native-curriculum.json \
        --grade-output /tmp/native-curriculum-grading.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.native_content import _pair, extras, grade, is_extended, media_url, rows_for
from app.api.native_lessons import _theory, plain, project_questions

CARD_TYPES = frozenset(('vocabulary', 'flashcards', 'card'))
NON_OBJECTIVE = frozenset(('self_review', 'self_assessed', 'writing', 'pronunciation'))
VISIBLE_QUESTION_FIELDS = ('prompt', 'instruction', 'context', 'section', 'translation', 'options', 'left_options', 'checklist')


def _text(value):
    if isinstance(value, dict):
        return '\n'.join(_text(item) for item in value.values())
    if isinstance(value, list):
        return '\n'.join(map(_text, value))
    return value if isinstance(value, str) else ''


def _visible(question):
    """Only fields decoded/displayed by the current SwiftUI CourseQuestion."""
    return _text({key: question.get(key) for key in VISIBLE_QUESTION_FIELDS})


def _identity(lesson):
    return {key: lesson[key] for key in ('file', 'level', 'module_order', 'lesson_number', 'type', 'external_key')}


def load_lessons(source):
    source = Path(source)
    files = [source] if source.is_file() else sorted(source.glob('*.json')) if source.is_dir() else []
    if not files:
        raise ValueError(f'No curriculum JSON files found: {source}')
    result = []
    for file in files:
        document = json.loads(file.read_text(encoding='utf-8'))
        module = document.get('module') if isinstance(document, dict) else None
        if not isinstance(module, dict) or not isinstance(module.get('lessons'), list):
            raise ValueError(f'Invalid module/lessons shape: {file.name}')
        for number, row in enumerate(module['lessons'], 1):
            if not isinstance(row, dict) or not isinstance(row.get('content'), dict) or not isinstance(row.get('type'), str):
                raise ValueError(f'Invalid lesson shape: {file.name} #{number}')
            content = deepcopy(row['content'])
            identity = {
                'file': file.name, 'level': module.get('level'),
                'module_order': module.get('order') or module.get('id'),
                'lesson_number': row.get('id') or row.get('order') or number,
                'type': row['type'], 'external_key': content.get('external_key'),
            }
            proxy = SimpleNamespace(
                id=len(result) + 1, number=identity['lesson_number'], order=row.get('order', number),
                title=row.get('title', row['type']), type=row['type'], content=content,
                module=SimpleNamespace(id=module.get('id'), number=identity['module_order'],
                                       level=SimpleNamespace(code=identity['level'])),
                module_id=module.get('id'), collection_id=None,
            )
            result.append({**identity, 'proxy': proxy})
    if not result:
        raise ValueError('Curriculum contains no lessons')
    return result


def projection_audit(lessons):
    """Check actual projected display, including intentional hiding by assessment."""
    issues, info, records, schemas = defaultdict(list), defaultdict(list), [], {}

    def issue(code, lesson, **detail):
        issues[code].append({**_identity(lesson), **detail})

    for lesson in lessons:
        proxy = lesson['proxy']
        content = proxy.content
        snapshot = deepcopy(content)
        record = _identity(lesson)
        records.append(record)
        if proxy.type not in schemas:
            sample = next((value[0] for value in content.values() if isinstance(value, list) and value), None)
            schemas[proxy.type] = {**record, 'content_keys': list(content), 'first_authored_item': sample}
        if proxy.type in CARD_TYPES:
            cards = content.get('cards') or content.get('vocabulary') or content.get('words') or content.get('items') or []
            bad = [index for index, row in enumerate(cards) if not isinstance(row, dict) or
                   not plain(row.get('front') or row.get('word') or row.get('english')) or
                   not plain(row.get('back') or row.get('translation') or row.get('russian'))]
            record.update(status='dedicated_cards_route', card_count=len(cards),
                          route='/api/native/lessons/<id>/cards/session')
            if not cards or bad:
                issue('card_source_shape_unusable', lesson, bad_rows=bad)
            continue
        try:
            questions = project_questions(proxy)
            base_theory = _theory(content)
            extra = extras(proxy) if is_extended(proxy) else {
                'theory': base_theory, 'assessment': 'theory_only' if not questions else 'graded',
            }
            raw = [] if proxy.type in ('writing_prompt', 'shadow_reading', 'idiom', 'pronunciation') else rows_for(proxy, content)
            assessment = extra.get('assessment')
            record.update(status='projected', question_count=len(questions), assessment=assessment,
                          inputs=dict(Counter(question.get('input', 'legacy_default') for question in questions)),
                          raw_theory_blocks=len(base_theory), rendered_theory_blocks=len(extra.get('theory', [])))
        except Exception as error:
            record.update(status='projection_error', error_type=type(error).__name__, code=getattr(error, 'code', None))
            issue('projection_error', lesson, error_type=type(error).__name__, code=getattr(error, 'code', None),
                  status=getattr(error, 'status', None), message=str(error))
            continue
        visible = _text({'questions': [{key: q.get(key) for key in VISIBLE_QUESTION_FIELDS} for q in questions],
                         'theory': extra.get('theory', []), 'instruction': extra.get('instruction')})
        # Lesson-wide and question audio must survive. Availability on the CDN
        # is deliberately outside this local, network-free structural audit.
        authored_audio = content.get('audio_url') or content.get('audio')
        if authored_audio:
            expected = media_url(authored_audio)
            if not expected or extra.get('audio_url') != expected:
                issue('required_lesson_audio_lost', lesson, authored=authored_audio, projected=extra.get('audio_url'))
        if raw and len(raw) != len(questions):
            issue('projected_question_count_mismatch', lesson, authored=len(raw), projected=len(questions))
        for index, (row, question) in enumerate(zip(raw, questions, strict=False)):
            shown = _visible(question)
            control = question.get('input') or ('choice' if question.get('options') else 'text')
            expected_options = None
            if control == 'order':
                expected_options = row.get('words') or row.get('tokens') or []
            elif control == 'choice' and row.get('type') not in ('true_false', 'tf'):
                expected_options = row.get('options') or []
            elif control == 'match':
                pairs = [_pair(pair) for pair in row.get('pairs') or []]
                expected_options = [right for _, right in pairs]
                expected_left = {str(i): plain(left) for i, (left, _) in enumerate(pairs)}
                left = question.get('left_options') or []
                if (len(left) != len(pairs)
                        or {item.get('value'): item.get('label') for item in left} != expected_left):
                    issue('matching_left_control_lost', lesson, question_index=index, projected_question=question)
            if expected_options is not None:
                options = question.get('options') or []
                expected_mapping = {str(i): plain(label) for i, label in enumerate(expected_options)}
                if (len(options) != len(expected_options)
                        or {option.get('value'): option.get('label') for option in options} != expected_mapping):
                    issue('answer_input_options_lost', lesson, question_index=index,
                          authored_options=expected_options, projected_question=question)
            if proxy.type == 'sentence_completion':
                for field in ('prompt_after', 'hint', 'context'):
                    value = plain(row.get(field))
                    if value and value.casefold() != 'vocab use' and value not in shown:
                        issue('sentence_completion_' + field + '_lost', lesson, question_index=index,
                              source_value=value, source_row=row, projected_question=question)
            if proxy.type == 'translation' and content.get('mode') == 'guided' and row.get('hint_words'):
                marker = 'Слова для перевода: '
                instruction = question.get('instruction', '')
                bank = instruction.split(marker, 1)[1].split('\n', 1)[0].split(' · ') if marker in instruction else []
                if Counter(map(plain, bank)) != Counter(map(plain, row['hint_words'])):
                    issue('guided_translation_wordbank_lost', lesson, question_index=index,
                          source_hint_words=row['hint_words'], projected_question=question)
            authored_audio = row.get('audio_url') or row.get('audio_clip_url') or row.get('audio')
            if authored_audio:
                expected = media_url(authored_audio)
                if not expected or expected != question.get('audio_url'):
                    issue('required_question_audio_lost', lesson, question_index=index,
                          authored=authored_audio, projected_question=question)
            if row.get('type') == 'listening_choice':
                transcript = plain(row.get('transcript') or row.get('audio_text') or row.get('text') or row.get('sentence'))
                # An explicitly authored question can itself quote a snippet;
                # the private transcript must not become additional display.
                display_only = _text({key: question.get(key) for key in ('prompt', 'context', 'instruction')})
                authored_question = _text({key: row.get(key) for key in ('question', 'prompt', 'context', 'instruction')})
                if transcript and len(transcript) > 8 and transcript in display_only and transcript not in authored_question:
                    issue('listening_transcript_leaked_in_prompt', lesson, question_index=index,
                          source_transcript=transcript, projected_question=question)
            if isinstance(row.get('dialogue'), list) and row.get('type') != 'listening_choice':
                for line in row['dialogue']:
                    if isinstance(line, dict):
                        text = plain(line.get('text'))
                        if line.get('blank') is True and not re.search(r'_{2,}', text):
                            text = '___'
                    else:
                        text = plain(line)
                    if text and text not in shown:
                        issue('dialogue_line_lost', lesson, question_index=index, source_text=text, projected_question=question)
        if proxy.type in ('reading', 'text') and isinstance(content.get('text'), dict):
            for index, line in enumerate(content['text'].get('lines', [])):
                text = plain(line.get('text')) if isinstance(line, dict) else plain(line)
                if text and text not in visible:
                    issue('reading_line_text_lost', lesson, line_index=index, source_text=text)
        if proxy.type in ('listening_immersion', 'shadow_reading'):
            text = plain(content.get('text') or content.get('transcript'))
            # Only a real objective listening assessment with authored questions
            # may hide this reference before answers. Confirmation practice must
            # show the text it asks the learner to study/repeat.
            if proxy.type == 'listening_immersion' and raw and assessment == 'practice':
                if text and text not in visible:
                    info['listening_comprehension_transcript_intentionally_hidden'].append(_identity(lesson))
            elif text and text not in visible:
                issue('self_assessed_listening_text_lost', lesson, assessment=assessment,
                      authored_question_count=len(raw), source_text=text)
        if proxy.type == 'writing_prompt':
            if plain(content.get('prompt')) and plain(content['prompt']) not in visible:
                issue('writing_prompt_lost', lesson)
            if content.get('checklist') and list(map(plain, content['checklist'])) != questions[0].get('checklist'):
                issue('writing_checklist_lost', lesson)
        if content != snapshot:
            issue('projection_mutated_source', lesson)
    return {
        'scope': 'Read-only in-memory native display audit; no create_app, database/session/network or deployment. Card queues require a separate SRS integration test.',
        'lesson_count': len(lessons), 'lesson_type_counts': dict(Counter(lesson['type'] for lesson in lessons)),
        'projection_status_counts': dict(Counter(record['status'] for record in records)),
        'assessment_counts': dict(Counter(record.get('assessment', 'dedicated_cards_or_error') for record in records)),
        'issue_counts': {key: len(value) for key, value in issues.items()},
        'issue_lesson_counts': {key: len({(x['file'], x['lesson_number'], x['type']) for x in value}) for key, value in issues.items()},
        'issues': dict(issues), 'informational_counts': {key: len(value) for key, value in info.items()},
        'informational': dict(info), 'schemas': schemas, 'records': records,
        'passed': not issues, 'database_access': False, 'app_started': False, 'source_changes_applied': False,
    }


def _ordering_indexes(words, expected):
    if not isinstance(words, list) or not isinstance(expected, str):
        raise ValueError('Reorder needs tokens and a canonical sentence')
    remaining, available, indexes = expected.strip(), set(range(len(words))), []
    while remaining and remaining.strip('.!?'):
        candidates = [index for index in available if remaining.lower().startswith(words[index].strip().lower())]
        if not candidates:
            raise ValueError('Canonical reorder answer cannot be assembled from authored tokens')
        index = max(candidates, key=lambda value: len(words[value].strip()))
        token = words[index].strip()
        if not token:
            raise ValueError('Empty reorder token')
        indexes.append(str(index))
        available.remove(index)
        remaining = remaining[len(token):].lstrip()
    if any(words[index].strip() not in ('.', '!', '?') for index in available):
        raise ValueError('Reorder answer leaves meaningful tokens unused')
    indexes.extend(str(index) for index in sorted(available))
    return json.dumps(indexes)


def _widget_answer(row, question):
    expected = next((row[key] for key in ('answer', 'correct_answer', 'correct', 'correct_index', 'correct_sentence', 'correct_order', 'english') if key in row and row[key] is not None), None)
    kind = question.get('input') or ('choice' if question.get('options') else 'text')
    if kind == 'match':
        return json.dumps({str(index): str(index) for index in range(len(row['pairs']))})
    if kind == 'order':
        if isinstance(expected, list):
            if all(type(value) is int for value in expected):
                return json.dumps(list(map(str, expected)))
            expected = ' '.join(map(str, expected))
        return _ordering_indexes(row.get('words') or row.get('tokens'), expected)
    if kind == 'choice':
        if row.get('type') in ('true_false', 'tf'):
            if type(expected) is bool:
                return 'true' if expected else 'false'
            if isinstance(expected, str) and expected.strip().lower() in ('true', '1', 'yes', 'false', '0', 'no'):
                return 'true' if expected.strip().lower() in ('true', '1', 'yes') else 'false'
            raise ValueError('Invalid canonical boolean')
        if 'correct_index' in row and expected == row['correct_index']:
            return str(expected)
        options = row.get('options') or []
        if isinstance(expected, str) and expected in options:
            return str(options.index(expected))
        if type(expected) is int or (isinstance(expected, str) and expected.isdigit()):
            return str(expected)
        raise ValueError(f'Canonical choice answer is not offered: {expected!r}')
    if isinstance(expected, list):
        expected = expected[0] if expected else None
    if not isinstance(expected, str) or not expected:
        raise ValueError('Empty or non-string canonical text answer')
    return expected


def grading_audit(lessons):
    failures, records, skips = [], [], Counter()
    question_count = 0
    for lesson in lessons:
        proxy, base = lesson['proxy'], _identity(lesson)
        if proxy.type in CARD_TYPES:
            skips['dedicated_cards'] += 1
            continue
        try:
            questions = project_questions(proxy)
            if not questions:
                skips['theory_only'] += 1
                continue
            assessment = extras(proxy)['assessment'] if is_extended(proxy) else 'graded'
            if assessment in NON_OBJECTIVE:
                skips[assessment] += 1
                continue
            rows = rows_for(proxy, proxy.content)
            answers = {question['id']: _widget_answer(row, question) for row, question in zip(rows, questions, strict=True)}
            result, feedback, assessment, _ = grade(proxy, questions, answers, 75)
            question_count += len(questions)
            wrong = [{'index': index, 'feedback': item, 'source_row': rows[index],
                      'transport_answer': answers[questions[index]['id']]}
                     for index, item in enumerate(feedback) if not item['correct']]
            record = {**base, 'questions': len(questions), 'assessment': assessment,
                      'score': result.get('score'), 'failed_count': len(wrong)}
            if proxy.type == 'listening_immersion' and rows:
                transcript = plain(proxy.content.get('text'))
                record['post_answer_transcript_available'] = bool(transcript and transcript in _text(feedback))
            records.append(record)
            if wrong:
                failures.append({**base, 'phase': 'canonical_answer_grading', 'failed': wrong})
        except Exception as error:
            failures.append({**base, 'phase': 'canonical_widget_or_grading',
                             'error_type': type(error).__name__, 'error': str(error)})
    return {
        'scope': 'Canonical objective native-widget/real-grader roundtrip, without database/app startup. Writing, self-review, confirmation and SRS queues excluded. This is not a semantic accuracy certificate.',
        'lesson_count': len(lessons), 'graded_lessons': len(records), 'graded_questions': question_count,
        'skip_counts': dict(skips), 'failure_count': len(failures), 'failures': failures, 'records': records,
        'passed': not failures, 'database_access': False, 'app_started': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, default=ROOT / 'module_completed' / 'fixed')
    parser.add_argument('--output', type=Path, help='Projection JSON report')
    parser.add_argument('--grade-output', type=Path, help='Also audit objective answers and write its JSON report')
    args = parser.parse_args(argv)
    try:
        source_path = args.source.resolve()
        for destination in (args.output, args.grade_output):
            if destination and (destination.resolve() == source_path
                                or (source_path.is_dir() and source_path in destination.resolve().parents)):
                raise ValueError('Audit reports must be outside the audited source path')
        lessons = load_lessons(args.source)
        report = projection_audit(lessons)
        grading = grading_audit(lessons) if args.grade_output else None
    except (ValueError, OSError, TypeError) as error:
        print(f'FAIL: {error}')
        return 2
    try:
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if args.grade_output:
            args.grade_output.write_text(json.dumps(grading, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError as error:
        print(f'FAIL: Cannot write audit report: {error}')
        return 2
    success = report['passed'] and (grading is None or grading['passed'])
    print(f"{'PASS' if success else 'FAIL'}: {report['lesson_count']} lessons; "
          f"{report['projection_status_counts'].get('projected', 0)} projected, "
          f"{report['projection_status_counts'].get('dedicated_cards_route', 0)} dedicated cards; "
          f"{sum(report['issue_counts'].values())} display issues")
    if grading:
        print(f"Objective roundtrip: {grading['graded_lessons']} lessons / {grading['graded_questions']} answers; {grading['failure_count']} failures")
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
