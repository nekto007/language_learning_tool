"""Regression tests for UI-004 / UI-005 (cross-zone audit 2026-08-08).

UI-004 — ``/words`` renders every word twice (table row + mobile card), and both
nodes stay in the DOM whichever one CSS hides. Counting nodes therefore reported
"40 слов выбрано" for 20 rows and the bulk request carried every id twice. The
mobile branch also hid the only "select all" control, which lived in the table
header.

UI-005 — ``main.js`` replaced every checkbox with a ``cloneNode(true)`` copy to
"remove existing listeners", which threw away the change handlers the template
had registered a moment earlier, so ticking one checkbox no longer opened the
bulk-actions panel.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORDS_TEMPLATE = ROOT / 'app' / 'templates' / 'words' / 'list_optimized.html'
MAIN_JS = ROOT / 'app' / 'static' / 'js' / 'main.js'
WORDS_CSS = ROOT / 'app' / 'static' / 'css' / 'words' / 'list_optimized.css'


@pytest.fixture(scope='module')
def words_template() -> str:
    return WORDS_TEMPLATE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def main_js() -> str:
    return MAIN_JS.read_text(encoding='utf-8')


class TestSelectionIsDeduplicated:
    def test_selection_helper_uses_a_set_of_ids(self, words_template):
        assert 'function getSelectedWordIdsUnique()' in words_template
        assert 'const ids = new Set();' in words_template

    def test_panel_counts_unique_ids_not_nodes(self, words_template):
        panel = words_template.split('function updateBulkActionsPanel()')[1]
        panel = panel.split('function ')[0]
        assert 'getSelectedWordIdsUnique()' in panel
        assert ".querySelectorAll('.word-checkbox:checked')" not in panel

    def test_bulk_update_sends_unique_ids(self, words_template):
        body = words_template.split('function bulkUpdateStatus(status)')[1]
        body = body.split('\nfunction ')[0]
        assert 'getSelectedWordIdsUnique()' in body
        assert ".querySelectorAll('.word-checkbox:checked')" not in body

    def test_twin_checkboxes_are_kept_in_sync(self, words_template):
        assert 'function syncTwinCheckbox(checkbox)' in words_template
        assert 'syncTwinCheckbox(checkbox);' in words_template


class TestMobileHasSelectAll:
    def test_mobile_select_all_control_exists(self, words_template):
        assert 'id="selectAllMobile"' in words_template

    def test_mobile_select_all_is_styled(self):
        assert '.vocab-mobile-selectall' in WORDS_CSS.read_text(encoding='utf-8')

    def test_mobile_select_all_is_inside_the_mobile_list(self, words_template):
        mobile_block = words_template.split('<div class="vocab-mobile-cards">')[1]
        assert 'id="selectAllMobile"' in mobile_block.split('{% endfor %}')[0]


def _strip_line_comments(source: str) -> str:
    return '\n'.join(
        line for line in source.splitlines() if not line.strip().startswith('//')
    )


class TestListenersSurvive:
    def test_bulk_setup_no_longer_clones_nodes(self, main_js):
        setup = main_js.split('function enhancedBulkActionsSetup()')[1]
        setup = _strip_line_comments(setup.split('\nfunction ')[0])
        assert 'cloneNode' not in setup
        assert 'replaceChild' not in setup

    def test_bulk_setup_binds_each_element_once(self, main_js):
        assert 'const bindOnce = (element, type, handler)' in main_js
        assert "element.dataset.bulkBound === type" in main_js

    def test_template_uses_delegated_change_handler(self, words_template):
        assert re.search(
            r"document\.addEventListener\('change', function", words_template,
        ), 'checkbox handling must survive node replacement by other scripts'


@pytest.fixture
def words_module(db_session, test_user):
    """Grant words module access to test_user (mirrors tests/test_words_routes.py)."""
    from app.modules.models import SystemModule, UserModule

    module = SystemModule.query.filter_by(code='words').first()
    if not module:
        module = SystemModule(
            code='words', name='Words', description='Words module',
            is_active=True, is_default=True, order=4,
        )
        db_session.add(module)
        db_session.flush()

    existing = UserModule.query.filter_by(
        user_id=test_user.id, module_id=module.id,
    ).first()
    if not existing:
        db_session.add(UserModule(
            user_id=test_user.id, module_id=module.id, is_enabled=True,
        ))
        db_session.commit()
    return module


class TestRenderedPage:
    def test_words_page_renders_both_controls(
        self, authenticated_client, db_session, words_module,
    ):
        from app.words.models import CollectionWords

        for i in range(3):
            db_session.add(CollectionWords(
                english_word=f'bulkword{i}', russian_word=f'слово{i}', level='A1',
            ))
        db_session.commit()

        response = authenticated_client.get('/words')

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'id="selectAll"' in html
        assert 'id="selectAllMobile"' in html
