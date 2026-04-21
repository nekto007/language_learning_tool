/**
 * Linear Daily Plan Context Tracker
 *
 * Remembers that the user entered a lesson via a linear-plan baseline slot
 * (`?from=linear_plan&slot=<kind>`) so the completion screen can offer
 * "next slot in plan" instead of curriculum-next.
 *
 * Priority of truth:
 *   1. Query-param on the current URL — primary source.
 *   2. sessionStorage (today's date only) — survival across in-lesson
 *      redirects that drop the query string.
 *
 * Lifecycle:
 *   - `init()` reads the query-param (or falls back to sessionStorage for
 *     today), validates the slot_kind, and writes/refreshes sessionStorage.
 *   - `clear()` removes the sessionStorage entry.
 *   - Navigation to `/dashboard` auto-clears (click capture). Cross-midnight
 *     entries are treated as stale and cleared on read.
 *
 * Safe with sessionStorage disabled (private mode, strict browsers): all
 * writes/reads are wrapped in try/catch and degrade to query-param-only.
 */
(function() {
  'use strict';

  var STORAGE_KEY = 'linear_plan_context';
  var PLAN_SOURCE = 'linear_plan';
  var VALID_SLOTS = ['curriculum', 'srs', 'book', 'error_review'];

  function _todayIsoDate() {
    var d = new Date();
    var mm = String(d.getMonth() + 1).padStart(2, '0');
    var dd = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + mm + '-' + dd;
  }

  function _isValidSlot(kind) {
    return typeof kind === 'string' && VALID_SLOTS.indexOf(kind) !== -1;
  }

  function _safeStorageGet() {
    try {
      var raw = window.sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function _safeStorageSet(payload) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      return true;
    } catch (e) {
      return false;
    }
  }

  function _safeStorageRemove() {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      /* ignore */
    }
  }

  function _readFromUrl() {
    var params;
    try {
      params = new URLSearchParams(window.location.search);
    } catch (e) {
      return null;
    }
    if (params.get('from') !== PLAN_SOURCE) return null;
    var slotKind = params.get('slot');
    if (!_isValidSlot(slotKind)) return null;
    return {
      date: _todayIsoDate(),
      slot_kind: slotKind,
      started_at: new Date().toISOString()
    };
  }

  function _readFromStorageForToday() {
    var stored = _safeStorageGet();
    if (!stored) return null;
    if (stored.date !== _todayIsoDate()) {
      _safeStorageRemove();
      return null;
    }
    if (!_isValidSlot(stored.slot_kind)) {
      _safeStorageRemove();
      return null;
    }
    return stored;
  }

  var _current = null;

  function init() {
    var fromUrl = _readFromUrl();
    if (fromUrl) {
      _safeStorageSet(fromUrl);
      _current = fromUrl;
      return _current;
    }
    _current = _readFromStorageForToday();
    return _current;
  }

  function isActive() {
    if (_current && _current.date === _todayIsoDate() && _isValidSlot(_current.slot_kind)) {
      return true;
    }
    _current = _readFromStorageForToday();
    return !!_current;
  }

  function getSlotKind() {
    if (!isActive()) return null;
    return _current ? _current.slot_kind : null;
  }

  function getContext() {
    if (!isActive()) return null;
    return _current ? {
      date: _current.date,
      slot_kind: _current.slot_kind,
      started_at: _current.started_at
    } : null;
  }

  function clear() {
    _current = null;
    _safeStorageRemove();
  }

  function _isDashboardHref(href) {
    if (!href || typeof href !== 'string') return false;
    try {
      var url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin) return false;
      return url.pathname === '/dashboard' || url.pathname.indexOf('/dashboard/') === 0;
    } catch (e) {
      return false;
    }
  }

  function _bindDashboardAutoClear() {
    document.addEventListener('click', function(ev) {
      var target = ev.target;
      while (target && target !== document) {
        if (target.tagName === 'A' && _isDashboardHref(target.getAttribute('href'))) {
          clear();
          return;
        }
        target = target.parentNode;
      }
    }, true);
  }

  /**
   * Fetch the next baseline slot from the API based on the current plan
   * context. Resolves to a plain object with the canonical shape:
   *   { next: {kind,url,title}|null, day_secured: bool, secured_just_now: bool }
   * Resolves to null when the context is not active, the request fails,
   * or the server returns a non-2xx response (e.g. 404 when the user is
   * not on the linear plan any more).
   */
  function fetchNextSlot() {
    if (!isActive()) return Promise.resolve(null);
    var url = '/api/daily-plan/next-slot';
    var kind = getSlotKind();
    if (kind) {
      url += '?current=' + encodeURIComponent(kind);
    }
    return fetch(url, {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    }).then(function(resp) {
      if (!resp || !resp.ok) return null;
      return resp.json().catch(function() { return null; });
    }).catch(function() { return null; });
  }

  /**
   * Apply plan-aware CTAs to the SRS (/study/cards) celebration screen when
   * the user reached it via ?from=linear_plan&slot=srs.
   *
   * Expects a DOM tree shaped like the celebration-actions block rendered by
   * ``components/_flashcard_session.html``:
   *   <div class="celebration-actions" data-celebration-actions>
   *     <div id="daily-plan-next-step"></div>
   *     <a id="session-extra-study-link" ...>Ещё карточки</a>
   *     <a id="fc-continue-btn" ...>К колодам</a>
   *   </div>
   *
   * On ``day_secured`` — redirects to ``/dashboard?day_secured=1`` and clears
   * the session context (handing off to the dashboard banner). On an
   * available next slot — swaps the primary/secondary CTAs for the plan
   * equivalents and sets ``data-completion-mode="plan"`` on the container so
   * the legacy curriculum-next link can be hidden via CSS if required.
   *
   * Returns a promise that resolves to the resulting completion mode
   * (``'plan'`` | ``'standalone'``) so callers and tests can chain on it.
   * Never throws: any failure degrades to standalone.
   */
  function applySrsPlanAwareCompletion(container) {
    if (!container) return Promise.resolve('standalone');
    if (!isActive() || getSlotKind() !== 'srs') {
      return Promise.resolve('standalone');
    }

    return fetchNextSlot().then(function(data) {
      if (!data || data.success === false) {
        return 'standalone';
      }
      if (data.day_secured) {
        try { clear(); } catch (e) { /* ignore */ }
        window.location.href = '/dashboard?day_secured=1';
        return 'plan';
      }
      if (!data.next || !data.next.url) {
        return 'standalone';
      }

      container.setAttribute('data-completion-mode', 'plan');

      // Hide legacy "Ещё карточки" (extra study) — irrelevant while user is
      // progressing through the plan.
      var extra = container.querySelector('#session-extra-study-link');
      if (extra) {
        extra.style.display = 'none';
        extra.setAttribute('aria-hidden', 'true');
      }

      // Drop any previously-injected plan CTAs (defensive: re-entry).
      var existing = container.querySelectorAll('[data-plan-cta]');
      Array.prototype.forEach.call(existing, function(node) {
        if (node.parentNode) node.parentNode.removeChild(node);
      });

      var continueBtn = container.querySelector('#fc-continue-btn');
      var continueWrapper = continueBtn ? continueBtn.parentNode : container;

      var primary = document.createElement('a');
      primary.className = 'btn-back-home btn-plan-next';
      primary.setAttribute('data-plan-cta', 'next-slot');
      primary.href = data.next.url;
      var primaryTitle = data.next.title
        ? 'Следующий слот плана · ' + data.next.title
        : 'Следующий слот плана';
      primary.textContent = primaryTitle;

      var secondary = document.createElement('a');
      secondary.className = 'btn-back-home btn-plan-dashboard';
      secondary.setAttribute('data-plan-cta', 'dashboard');
      secondary.href = '/dashboard';
      secondary.textContent = 'На дашборд';

      if (continueBtn) {
        continueBtn.style.display = 'none';
        continueBtn.setAttribute('aria-hidden', 'true');
        continueWrapper.insertBefore(primary, continueBtn);
        continueWrapper.insertBefore(secondary, continueBtn);
      } else {
        container.appendChild(primary);
        container.appendChild(secondary);
      }
      return 'plan';
    }).catch(function() {
      return 'standalone';
    });
  }

  window.linearPlanContext = {
    init: init,
    isActive: isActive,
    getSlotKind: getSlotKind,
    getContext: getContext,
    clear: clear,
    fetchNextSlot: fetchNextSlot,
    applySrsPlanAwareCompletion: applySrsPlanAwareCompletion,
    STORAGE_KEY: STORAGE_KEY,
    VALID_SLOTS: VALID_SLOTS.slice()
  };

  init();
  _bindDashboardAutoClear();
})();
