"""Regression tests for CNT-011 / CNT-012 / CNT-013 (cross-zone audit 2026-08-08).

CNT-011 — ``python scripts/validate_corpus.py`` (the documented invocation) put
``scripts/`` on ``sys.path[0]``, so ``import app`` failed, the runtime schema check
was silently skipped, and the gate still printed ``PASS``. A gate that promises to
"reject exactly what the admin re-import would reject" must not pass while the
schema is unreachable.

CNT-012 — ``sentence_completion`` items whose gap opens the sentence legitimately
carry an empty ``prompt``; the text lives in ``context`` / ``prompt_after`` and the
template renders it that way. The validator flagged 29 of them as blocking
``empty-required-field``, which would have vetoed a correct re-import under
``--strict``.

CNT-013 — the DB branch of ``diff_module_json_against_db.py`` (and its twin in
``audit_module_completed_json_gaps.py``) was dead: ``create_app("development")``
fed a *string* to ``app.config.from_object``, and the ``db`` it imported was the
root ``extensions.db``, an instance the app is never registered with.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_module_completed_json import _detect_empty_required_fields

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT_ROOT / 'scripts'


def _module_ast(name: str) -> ast.Module:
    return ast.parse((SCRIPTS / name).read_text(encoding='utf-8'))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name} not found')


class TestValidateCorpusSchemaGate:
    """CNT-011 — the documented invocation must reach the runtime schema."""

    def test_project_root_is_on_sys_path_before_app_import(self):
        source = (SCRIPTS / 'validate_corpus.py').read_text(encoding='utf-8')
        insert_at = source.index('sys.path.insert')
        import_at = source.index('from app.curriculum.validators import LessonContentValidator')
        assert insert_at < import_at, 'sys.path must be fixed before the app import is attempted'

    def test_documented_invocation_imports_the_validator(self):
        """`python scripts/validate_corpus.py` from the project root, no PYTHONPATH."""
        proc = subprocess.run(
            [sys.executable, 'scripts/validate_corpus.py'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(Path.home())},
        )
        # Positive assertions first: two "substring is absent" checks also pass
        # when the script died before printing anything at all.
        assert proc.returncode in (0, 1), (proc.returncode, proc.stderr[:2000])
        assert 'CORPUS VALIDATION' in proc.stdout, proc.stdout[:2000]
        assert 'LessonContentValidator unavailable' not in proc.stdout, proc.stdout[:2000]
        assert 'schema check skipped' not in proc.stdout, proc.stdout[:2000]

    def test_an_empty_corpus_is_a_failure_not_a_pass(self):
        """module_completed/ is gitignored — zero files must not report PASS."""
        source = (SCRIPTS / 'validate_corpus.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        body = ast.unparse(_function(tree, 'main'))
        guard_at = body.index('if not files:')
        loop_at = body.index('for fp in files:')
        assert guard_at < loop_at
        assert 'E(' in body[guard_at:loop_at], 'an empty corpus must raise a blocking ERROR'

    def test_missing_validator_is_a_blocking_error_not_a_note(self):
        """Without the schema the gate must fail, not print PASS with a footnote."""
        source = (SCRIPTS / 'validate_corpus.py').read_text(encoding='utf-8')
        handler = source.split('except Exception as _e:', 1)[1].split('for fp in files:', 1)[0]
        assert 'E(' in handler, 'unreachable schema must raise a blocking ERROR'
        assert 'print(' not in handler, 'a bare print leaves the run reporting PASS'


class TestSentenceCompletionEmptyPrompt:
    """CNT-012 — a leading gap is a legal shape, not an empty required field."""

    def test_leading_gap_with_prompt_after_is_accepted(self):
        content = {
            'items': [
                {'answer': 'Never', 'prompt': '', 'prompt_after': 'have I seen such a thing.'},
            ]
        }
        assert _detect_empty_required_fields('sentence_completion', content) == []

    def test_leading_gap_with_context_only_is_accepted(self):
        content = {'items': [{'answer': 'Never', 'prompt': '', 'context': 'Formal inversion.'}]}
        assert _detect_empty_required_fields('sentence_completion', content) == []

    def test_item_with_no_text_at_all_is_still_flagged(self):
        content = {'items': [{'answer': 'Never', 'prompt': '', 'prompt_after': '', 'context': ''}]}
        issues = _detect_empty_required_fields('sentence_completion', content)
        assert [path for path, _ in issues] == ['items[0].prompt']

    def test_missing_answer_is_still_flagged(self):
        content = {'items': [{'answer': '', 'prompt': 'I have ___ been there.'}]}
        issues = _detect_empty_required_fields('sentence_completion', content)
        assert [path for path, _ in issues] == ['items[0].answer']

    def test_live_corpus_has_no_empty_required_field_errors(self):
        """The 29 findings the audit measured were all of this shape."""
        source_dir = PROJECT_ROOT / 'module_completed' / 'fixed'
        if not source_dir.is_dir():
            pytest.skip('corpus is gitignored and absent in this checkout')
        import json

        offenders = []
        for path in sorted(source_dir.glob('*.json')):
            module = json.loads(path.read_text(encoding='utf-8')).get('module') or {}
            for lesson in module.get('lessons') or []:
                content = lesson.get('content')
                if not isinstance(content, dict):
                    continue
                offenders += [
                    (path.name, lesson.get('type'), p)
                    for p, _ in _detect_empty_required_fields(lesson.get('type'), content)
                ]
        assert offenders == []


class TestDiffScriptsCanReachTheDatabase:
    """CNT-013 — both audit tools must build a real app bound to the real session."""

    @pytest.mark.parametrize(
        'script', ['diff_module_json_against_db.py', 'audit_module_completed_json_gaps.py']
    )
    def test_create_app_is_called_without_a_config_name(self, script):
        fn = _function(_module_ast(script), '_try_get_db_session')
        calls = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'create_app'
        ]
        assert len(calls) == 1
        call = calls[0]
        assert not call.args and not call.keywords, (
            'create_app takes a config object; a string reaches '
            'app.config.from_object -> import_string() and raises'
        )

    @pytest.mark.parametrize(
        'script', ['diff_module_json_against_db.py', 'audit_module_completed_json_gaps.py']
    )
    def test_db_comes_from_the_instance_the_app_registers(self, script):
        fn = _function(_module_ast(script), '_try_get_db_session')
        modules = {node.module for node in ast.walk(fn) if isinstance(node, ast.ImportFrom)}
        assert 'app.utils.db' in modules
        assert 'extensions' not in modules, (
            'root extensions.db is a second SQLAlchemy instance; querying through it '
            'raises "The current Flask app is not registered with this SQLAlchemy instance"'
        )

    @pytest.mark.parametrize(
        'script', ['diff_module_json_against_db.py', 'audit_module_completed_json_gaps.py']
    )
    def test_project_root_is_on_sys_path_inside_the_helper(self, script):
        fn = _function(_module_ast(script), '_try_get_db_session')
        assert 'sys.path.insert' in ast.unparse(fn)
