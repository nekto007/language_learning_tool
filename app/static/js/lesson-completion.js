/**
 * Lesson completion renderer (single owner of the lesson-page completion screen).
 *
 * Extracted verbatim from the inline showLessonCompletion in
 * lesson_base_template.html (now a thin shim) so the same logic can be reused
 * across surfaces — stage 2 of the lesson-completion-contract migration, see
 * docs/design/lesson-completion-contract.md §2.3.
 *
 * Labels come from window.I18N (rendered server-side by
 * components/_lesson_i18n.html) because an external .js file cannot call Jinja's
 * _(); a Russian fallback keeps it working if the bridge ever fails to load.
 *
 * window.LessonCompletion.show(opts), opts = { score, grade_name,
 * daily_plan_ctx, silent }. Behaviour is identical to the legacy inline helper:
 *   1. inline daily_plan_ctx → update the server-rendered [data-plan-cta]
 *      anchors in place / day-secured redirect (no fetch);
 *   2. plan context but NO inline ctx → fetchNextSlot() fallback (retired in a
 *      later stage once every call-site forwards the inline ctx);
 *   3. otherwise → reveal the standalone (catalog) CTAs.
 */
(function () {
  'use strict';

  function _t(key, fallback) {
    var dict = window.I18N || {};
    return (typeof dict[key] === 'string' && dict[key]) ? dict[key] : fallback;
  }

  function _setLeadingText(anchor, text) {
    // Replace the anchor's leading text node, preserving child elements (e.g.
    // the chevron SVG) that a blunt textContent assignment would wipe.
    var node = anchor.firstChild;
    while (node && node.nodeType !== Node.TEXT_NODE) {
      node = node.nextSibling;
    }
    if (node) {
      node.nodeValue = text + ' ';
    } else {
      anchor.insertBefore(document.createTextNode(text + ' '), anchor.firstChild);
    }
  }

  function show(opts) {
    opts = opts || {};
    var el = document.getElementById('lesson-completion');
    if (!el) return;
    var gradeEl = document.getElementById('completion-grade');
    var scoreEl = document.getElementById('completion-score');
    if (gradeEl && opts.grade_name) {
      gradeEl.textContent = opts.grade_name;
    }
    if (scoreEl && opts.score !== undefined) {
      scoreEl.textContent = Math.round(opts.score) + '%';
    }

    function _hideLegacyFooter() {
      var legacyFooter = document.getElementById('lesson-footer');
      if (legacyFooter) {
        legacyFooter.classList.remove('lsn-footer--visible');
        legacyFooter.style.display = 'none';
      }
      var legacyDailyPlan = document.getElementById('daily-plan-next-step');
      if (legacyDailyPlan) {
        legacyDailyPlan.style.display = 'none';
      }
    }

    function _revealCompletion(mode) {
      el.setAttribute('data-completion-mode', mode);
      el.style.display = 'block';
      if (mode === 'plan') {
        _hideLegacyFooter();
      }
      if (!opts.silent) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      document.dispatchEvent(new Event('dailyPlanStepComplete'));
    }

    function _renderPlanCtas(nextUrl, nextTitle, dashboardUrl) {
      var actions = document.getElementById('completion-actions');
      if (!actions) return;
      var nextBtn = actions.querySelector('[data-plan-cta="next-slot"]');
      if (nextBtn && nextUrl) {
        nextBtn.setAttribute('href', nextUrl);
        _setLeadingText(nextBtn, _t('plan_next', 'Следующий урок плана'));
        nextBtn.style.display = '';
      }
      var dashBtn = actions.querySelector('[data-plan-cta="dashboard"]');
      if (dashBtn) {
        if (dashboardUrl) {
          dashBtn.setAttribute('href', dashboardUrl);
        }
        _setLeadingText(dashBtn, _t('dashboard', 'На дашборд'));
        dashBtn.style.display = '';
      }
    }

    var ctx = window.linearPlanContext;
    var inPlanContext = !!(ctx && typeof ctx.isActive === 'function' && ctx.isActive());

    // Prefer the refreshed daily_plan_ctx from the submit response when the
    // caller hands one over — already keyed to the just-completed lesson, and
    // saves the extra fetchNextSlot round-trip.
    if (opts.daily_plan_ctx && opts.daily_plan_ctx.is_daily_plan) {
      var dp = opts.daily_plan_ctx;
      if (dp.day_secured && !dp.next_slot_url) {
        try { if (ctx && typeof ctx.clear === 'function') { ctx.clear(); } } catch (_e) {}
        window.location.href = (dp.dashboard_url || '/dashboard') + '?day_secured=1';
        return;
      }
      _renderPlanCtas(dp.next_slot_url, dp.next_slot_title, dp.dashboard_url);
      _revealCompletion('plan');
      return;
    }

    if (!inPlanContext) {
      _revealCompletion('standalone');
      return;
    }

    // Plan context but no inline ctx — ask the server which baseline slot is
    // next. Stage 3 forwards the inline ctx from every call-site, retiring this.
    var fetcher = (ctx && typeof ctx.fetchNextSlot === 'function') ? ctx.fetchNextSlot : null;
    if (!fetcher) {
      _revealCompletion('standalone');
      return;
    }
    fetcher().then(function (data) {
      if (!data) {
        _revealCompletion('standalone');
        return;
      }
      if (data.day_secured && !data.next) {
        try { if (ctx && typeof ctx.clear === 'function') { ctx.clear(); } } catch (_e) {}
        window.location.href = '/dashboard?day_secured=1';
        return;
      }
      var next = data.next || {};
      _renderPlanCtas(next.url, next.title, '/dashboard');
      _revealCompletion('plan');
    }).catch(function () {
      _revealCompletion('standalone');
    });
  }

  window.LessonCompletion = { show: show };
})();
