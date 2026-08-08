"""Regression tests for the UI P2/P3 findings closed in Task 9.

Cross-zone audit 2026-08-08 (docs/audit/2026-08-08-cross-zone-audit.md):

* **UI-008** a Jinja ``_()`` call shipped verbatim into a ``<script>`` body, so
  the catch handler died with ``ReferenceError`` before showing its message —
  and the setup UI had already been hidden, leaving a blank screen.
* **UI-009** the SRS MutationObserver re-derived plan CTAs that
  ``flashcard-session.js`` had already applied from the inline
  ``daily_plan_ctx``, and could hard-redirect over them ~200ms later.
* **UI-010** grade/score were written into a ``display:none`` container, so the
  ``aria-live`` region announced nothing and focus stayed on a button that plan
  mode then hid.
* **UI-011 / UI-012** silent failures: empty ``catch``, no ``resp.ok``.
* **UI-013** the plan bar offset the page twice (48px padding + 48px margin).
* **UI-015 / UI-016** keyboard dead ends: a click-only ``<div>`` menu and a
  modal with no role, focus move, Escape or focus return.
* **UI-017** 31 explicit ``behavior:'smooth'`` calls ignored reduced motion.
* **UI-022 / UI-024** progress and selection state never reached assistive tech.
* **UI-029** JS-injected CTA labels bypassed ``window.I18N``.
* **UI-031 / UI-035 / UI-036 / UI-037** dead files.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JS = REPO / 'app' / 'static' / 'js'
TPL = REPO / 'app' / 'templates'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


# Cyrillic range, spelled by code point so the pattern itself stays ASCII.
CYRILLIC = '[\u0410-\u044f\u0401\u0451]'


class TestJinjaCallsNeverShipToTheBrowser:
    """UI-008."""

    @pytest.mark.parametrize('template', [
        'curriculum/lessons/matching.html',
        'study/matching.html',
    ])
    def test_no_bare_underscore_call_in_script_body(self, template):
        source = _read(TPL / template)
        # `_('...')` outside {{ }} / {% %} reaches the browser as-is, and there
        # is no global `_` in this project.
        stripped = re.sub(r'\{\{.*?\}\}|\{%.*?%\}', '', source, flags=re.S)
        assert not re.search(r"(?<![\w.$])_\(\s*['\"]", stripped)

    def test_no_project_javascript_defines_a_global_underscore(self):
        """The premise of the bug: nothing provides `_` at runtime."""
        for path in JS.rglob('*.js'):
            if 'min.js' in path.name or 'bundle' in path.name:
                continue
            source = _read(path)
            assert 'window._ =' not in source
            assert 'function _(' not in source

    def test_failed_game_start_restores_the_setup_ui(self):
        source = _read(TPL / 'curriculum/lessons/matching.html')
        catch_block = source.split('} catch (error) {', 1)[1][:400]
        assert 'elements.gameSetup.style.display' in catch_block


class TestFetchFailuresAreVisible:
    """UI-011, UI-012."""

    def test_annotation_save_checks_response_ok(self):
        source = _read(TPL / 'curriculum/lessons/vocabulary.html')
        assert 'showAnnotationError' in source
        assert '.catch(function() {})' not in source, 'an empty catch swallows the failure'

    def test_add_to_list_reports_failure(self):
        source = _read(TPL / 'curriculum/lessons/vocabulary.html')
        assert 'word-add-to-list__btn--failed' in source

    def test_complete_theory_guards_on_response_ok(self):
        source = _read(JS / 'grammar' / 'topic-detail.js')
        assert 'if (!response.ok)' in source
        assert 'showTheoryError' in source

    def test_complete_theory_disables_the_button_while_in_flight(self):
        source = _read(JS / 'grammar' / 'topic-detail.js')
        assert 'btn.disabled = true' in source
        assert "btn.classList.add('btn--loading')" in source

    def test_complete_theory_settles_on_a_repeat_click(self):
        """The endpoint is idempotent: xp_earned == 0 is success, not silence."""
        source = _read(JS / 'grammar' / 'topic-detail.js')
        mark_at = source.index('markTheoryButtonDone(btn);', source.index('const data = await'))
        xp_at = source.index('data.xp_earned > 0')
        assert mark_at < xp_at


class TestCompletionAnnouncement:
    """UI-010."""

    def test_result_is_written_after_the_container_is_revealed(self):
        source = _read(JS / 'lesson-completion.js')
        reveal_at = source.index("el.style.display = 'block'")
        fill_at = source.index('_fillResult();', reveal_at)
        assert reveal_at < fill_at

    def test_focus_moves_into_the_completion_panel(self):
        source = _read(JS / 'lesson-completion.js')
        assert 'el.focus({ preventScroll: true })' in source

    def test_the_panel_is_focusable(self):
        source = _read(TPL / 'lesson_base_template.html')
        block = source[source.index('id="lesson-completion"') - 200:]
        assert 'tabindex="-1"' in block[:400]


class TestPlanBarOffset:
    """UI-013."""

    def test_body_padding_is_not_added_on_top_of_the_navbar_margin(self):
        source = _read(TPL / 'components/_daily_plan_progress.html')
        assert "document.body.style.paddingTop = '48px'" not in source

    def test_the_css_offset_is_still_declared(self):
        source = _read(TPL / 'components/_daily_plan_progress.html')
        assert 'margin-top: 48px' in source


class TestKeyboardReachability:
    """UI-015, UI-016."""

    def test_bottom_nav_more_is_a_button_in_the_tab_order(self):
        source = _read(TPL / 'base.html')
        block = source[source.index('id="bottom-nav-more"') - 200:][:600]
        assert 'role="button"' in block
        assert 'tabindex="0"' in block
        assert 'aria-expanded' in block

    def test_bottom_nav_more_handles_enter_space_and_escape(self):
        source = _read(TPL / 'base.html')
        block = source[source.index("var moreBtn = document.getElementById('bottom-nav-more')"):][:2400]
        assert "moreBtn.addEventListener('keydown'" in block
        assert "e.key === 'Enter'" in block
        assert "e.key === 'Escape'" in block

    def test_levelup_modal_declares_dialog_semantics(self):
        source = _read(TPL / 'base.html')
        block = source[source.index('id="levelup-modal"'):][:600]
        assert 'role="dialog"' in block
        assert 'aria-modal="true"' in block
        assert 'aria-labelledby="levelup-title"' in block

    def test_levelup_modal_moves_and_restores_focus(self):
        source = _read(TPL / 'base.html')
        assert 'function openLevelupModal()' in source
        assert 'function closeLevelupModal()' in source
        assert 'levelupOpener.focus()' in source

    def test_levelup_modal_closes_on_escape_and_traps_tab(self):
        source = _read(TPL / 'base.html')
        block = source[source.index('function openLevelupModal()'):][:2600]
        assert "e.key === 'Escape'" in block
        assert "e.key !== 'Tab'" in block

    def test_only_the_helper_opens_the_modal(self):
        source = _read(TPL / 'base.html')
        # Exactly one writer, and it lives inside openLevelupModal().
        assert source.count("modal.style.display = 'flex'") == 1
        helper = source[source.index('function openLevelupModal()'):]
        assert "modal.style.display = 'flex'" in helper[:400]
        assert source.count('openLevelupModal();') == 2, 'both celebration paths go through it'


class TestReducedMotion:
    """UI-017."""

    def test_smooth_scroll_is_downgraded_globally(self):
        source = _read(TPL / 'base.html')
        assert 'prefers-reduced-motion: reduce' in source
        assert 'Element.prototype.scrollIntoView' in source
        assert "behavior: 'auto'" in source

    def test_the_shim_loads_before_any_deferred_script(self):
        source = _read(TPL / 'base.html')
        shim_at = source.index('Element.prototype.scrollIntoView')
        body_at = source.index('<body')
        assert shim_at < body_at, 'the shim must be installed before page scripts run'


class TestAriaState:
    """UI-022, UI-024."""

    def test_sentence_completion_updates_aria_valuenow(self):
        source = _read(TPL / 'curriculum/lessons/sentence_completion.html')
        assert "setAttribute('aria-valuenow'" in source
        assert '_setProgressValue(' in source

    def test_book_details_progress_reports_a_key_that_exists(self):
        source = _read(TPL / 'books/details.html')
        assert "word_stats['queued']" not in source

    def test_sentence_correction_options_are_radios(self):
        source = _read(TPL / 'curriculum/lessons/sentence_correction.html')
        assert source.count('role="radiogroup"') == 2, 'both the items and legacy branches'
        assert 'role="radio"\n' in source or 'role="radio"' in source
        # aria-pressed may survive only inside the explanatory comments.
        code_lines = [
            line for line in source.splitlines()
            if 'aria-pressed' in line and not line.strip().startswith(('#', '{#', '//', '*'))
            and 'aria-pressed described' not in line and 'rendered aria-pressed' not in line
        ]
        assert code_lines == []

    def test_sentence_correction_reflects_the_pick(self):
        source = _read(TPL / 'curriculum/lessons/sentence_correction.html')
        assert source.count("setAttribute('aria-checked'") >= 2

    def test_listening_speed_group_has_radio_children(self):
        source = re.sub(
            r'\{#.*?#\}', '', _read(TPL / 'curriculum/lessons/listening_immersion.html'), flags=re.S
        )
        start = source.index('id="audio-speed-controls"')
        block = source[start:source.index('</div>', start)]
        # `role="radiogroup"` contains `role="radio"` as a substring — count the
        # children by the attribute pair they actually carry.
        assert block.count('role="radio" aria-checked') == 4
        assert block.count('role="radiogroup"') == 1

    def test_listening_speed_updates_aria_checked(self):
        source = _read(TPL / 'curriculum/lessons/listening_immersion.html')
        assert "btn.setAttribute('aria-checked', active ? 'true' : 'false')" in source

    def test_final_test_matching_buttons_expose_selection(self):
        source = _read(TPL / 'curriculum/lessons/final_test.html')
        assert source.count("setAttribute('aria-pressed'") >= 4


class TestSrsObserverRace:
    """UI-009 — scoped: the observer stays, the double-render does not."""

    def test_inline_context_claims_the_container(self):
        source = _read(JS / 'flashcard-session.js')
        assert "setAttribute('data-plan-cta-source', 'inline')" in source

    def test_the_claim_happens_before_the_screen_is_revealed(self):
        """Revealing the screen is what wakes the observer."""
        source = _read(JS / 'flashcard-session.js')
        claim_at = source.index("'data-plan-cta-source', 'inline'")
        reveal_at = source.index('this._showCelebration(', claim_at)
        assert claim_at < reveal_at

    def test_the_observer_stands_down_when_claimed(self):
        source = _read(TPL / 'components/_flashcard_session.html')
        assert "getAttribute('data-plan-cta-source') === 'inline'" in source

    def test_the_observer_still_exists_for_study_cards(self):
        source = _read(TPL / 'components/_flashcard_session.html')
        assert 'new MutationObserver' in source
        assert 'applySrsPlanAwareCompletion' in source


class TestJsI18nRouting:
    """UI-029 — scoped to the daily-plan files named in the remediation plan."""

    KEYS = [
        'plan_next_slot', 'plan_continue', 'reading_slot_done', 'day_saved', 'hide',
        'skip_step_failed', 'step_unknown', 'finish_previous_first',
        'catalog_loading', 'catalog_failed', 'choice_saving', 'choice_failed',
        'no_books_for_level', 'task_added_one', 'tasks_added_many',
    ]

    @pytest.mark.parametrize('key', KEYS)
    def test_bridge_exposes_the_key(self, key):
        source = _read(TPL / 'components/_lesson_i18n.html')
        assert f'{key}:' in source

    @pytest.mark.parametrize('module', ['linear-plan-context.js', 'linear-daily-plan.js'])
    def test_module_reads_through_the_bridge(self, module):
        source = _read(JS / module)
        assert 'window.I18N' in source
        assert 'function _t(' in source

    @pytest.mark.parametrize('module', ['linear-plan-context.js', 'linear-daily-plan.js'])
    def test_no_bare_cyrillic_ui_literal_remains(self, module):
        source = _read(JS / module)
        offenders = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith('*') or stripped.startswith('//') or stripped.startswith('/*'):
                continue
            if not re.search("['\"][^'\"]*" + CYRILLIC, line):
                continue
            if '_t(' in line:
                continue
            offenders.append(stripped)
        assert offenders == [], offenders

    def test_fallbacks_keep_the_current_locale_rendering(self):
        """Every _t() call must carry the Russian string as its fallback."""
        for module in ('linear-plan-context.js', 'linear-daily-plan.js'):
            for call in re.findall(r"_t\('([a-z_]+)',\s*'([^']*)'\)", _read(JS / module)):
                assert re.search(CYRILLIC, call[1]), call


class TestDeadCodeIsGone:
    """UI-031, UI-035, UI-036, UI-037."""

    @pytest.mark.parametrize('relative', [
        'js/daily-plan-next.js',
        'js/dashboard.js',
        'js/book_processing.js',
        'js/speech_api.js',
        'js/study-guide.js',
        'js/words/dashboard_path.js',
        'css/dashboard.css',
        'css/study-guide.css',
        'css/lesson-styles.css',
        'css/mobile-reader.css',
        'css/reader.css',
        'css/study.css',
        'css/style.css',
        'css/unified-styles.css',
        'css/landing.css',
    ])
    def test_asset_is_deleted(self, relative):
        assert not (REPO / 'app' / 'static' / relative).exists()

    @pytest.mark.parametrize('relative', [
        'words/dashboard.html',
        'admin/curriculum/srs_settings.html',
        'books/reading_widget.html',
        'curriculum/book_courses/lessons/grammar.html',
        'curriculum/book_courses/lessons/reading_assignment.html',
    ])
    def test_orphan_template_is_deleted(self, relative):
        assert not (TPL / relative).exists()

    @pytest.mark.parametrize('name', [
        'daily-plan-next.js', 'dashboard.js', 'book_processing.js', 'speech_api.js',
        'study-guide.js', 'dashboard_path.js', 'dashboard.css', 'study-guide.css',
        'lesson-styles.css', 'mobile-reader.css', 'unified-styles.css', 'landing.css',
    ])
    def test_no_template_references_the_deleted_asset(self, name):
        hits = [p.name for p in TPL.rglob('*.html') if f"filename='{'js' if name.endswith('.js') else 'css'}/" in _read(p) and name in _read(p)]
        assert hits == []

    def test_book_details_no_longer_renders_the_orphaned_placeholder(self):
        """book_processing.js was the only writer of #processing-status."""
        assert 'processing-status' not in _read(TPL / 'books/details.html')

    def test_pronunciation_still_has_its_own_speech_recognition(self):
        """speech_api.js was a superseded duplicate, not the live implementation."""
        source = _read(TPL / 'curriculum/lessons/pronunciation.html')
        assert 'webkitSpeechRecognition' in source

    def test_book_course_grammar_lessons_still_route_somewhere_real(self):
        """The deleted grammar.html/reading_assignment.html were never rendered."""
        routes = _read(REPO / 'app' / 'curriculum' / 'routes' / 'book_courses.py')
        assert 'book_courses/lessons/language_focus.html' in routes
        assert 'book_courses/lessons/grammar_bridge.html' in routes
        assert 'book_courses/lessons/reading_passage.html' in routes
        assert "'curriculum/book_courses/lessons/grammar.html'" not in routes
        assert "'curriculum/book_courses/lessons/reading_assignment.html'" not in routes
