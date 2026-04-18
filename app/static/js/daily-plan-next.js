/**
 * Daily Plan Next Step Banner & Auto-redirect
 *
 * Shows a "next step" banner when user completes a daily plan activity.
 * When ?from=daily_plan is in the URL, also shows a modal overlay with
 * auto-redirect countdown on step completion.
 */
(function() {
  'use strict';

  // Escape HTML special characters to prevent XSS
  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  // Only activate if user came from daily plan
  var params = new URLSearchParams(window.location.search);
  if (params.get('from') !== 'daily_plan') return;

  // Find placeholder container
  var container = document.getElementById('daily-plan-next-step');

  // Inject banner styles once
  var style = document.createElement('style');
  style.textContent =
    '.daily-next-banner{display:flex;align-items:center;gap:.75rem;padding:.875rem 1.25rem;' +
    'background:linear-gradient(135deg,#5046e5 0%,#7c3aed 100%);color:#fff;border-radius:12px;' +
    'text-decoration:none;font-family:"Onest",-apple-system,BlinkMacSystemFont,sans-serif;' +
    'font-weight:600;font-size:.9375rem;transition:transform .2s,box-shadow .2s;margin-bottom:.75rem;width:100%;}' +
    '.daily-next-banner:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(80,70,229,.4);color:#fff;}' +
    '.daily-next-banner--done{background:linear-gradient(135deg,#10b981 0%,#059669 100%);}' +
    '.daily-next-banner--done:hover{box-shadow:0 4px 16px rgba(16,185,129,.4);}' +
    '.daily-next-banner__icon{font-size:1.375rem;flex-shrink:0;line-height:1;}' +
    '.daily-next-banner__text{flex:1;line-height:1.3;}' +
    '.daily-next-banner__progress{font-size:.75rem;opacity:.85;font-weight:500;margin-top:.125rem;}' +
    '.daily-next-banner__arrow{font-size:1.25rem;flex-shrink:0;opacity:.8;}' +
    /* Modal overlay styles */
    '.dp-modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;' +
    'background:rgba(0,0,0,0.6);z-index:10000;display:flex;align-items:center;' +
    'justify-content:center;font-family:"Onest",-apple-system,BlinkMacSystemFont,sans-serif;}' +
    '.dp-modal{background:#fff;border-radius:16px;padding:2rem 2.5rem;text-align:center;' +
    'max-width:400px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.3);animation:dp-modal-in .3s ease;}' +
    '@keyframes dp-modal-in{from{opacity:0;transform:scale(0.9);}to{opacity:1;transform:scale(1);}}' +
    '.dp-modal__icon{font-size:3rem;margin-bottom:.75rem;}' +
    '.dp-modal__title{font-size:1.25rem;font-weight:700;color:#1e1b4b;margin-bottom:.5rem;}' +
    '.dp-modal__countdown{font-size:.9375rem;color:#6b7280;margin-bottom:1.25rem;}' +
    '.dp-modal__btn{display:inline-block;background:linear-gradient(135deg,#5046e5,#7c3aed);' +
    'color:#fff;text-decoration:none;padding:10px 24px;border-radius:8px;font-weight:600;' +
    'font-size:.9375rem;transition:transform .15s,box-shadow .15s;margin-bottom:.75rem;}' +
    '.dp-modal__btn:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(80,70,229,.4);color:#fff;}' +
    '.dp-modal__btn--done{background:linear-gradient(135deg,#10b981,#059669);}' +
    '.dp-modal__cancel{display:block;color:#9ca3af;font-size:.8125rem;text-decoration:none;cursor:pointer;border:none;background:none;margin:0 auto;}' +
    '.dp-modal__cancel:hover{color:#6b7280;}';
  document.head.appendChild(style);

  // Debounce guard
  var lastShownAt = 0;
  var modalShown = false;

  var isMissionPlan = !!document.querySelector('[data-mission-plan]');

  // Listen for completion event from each page's own logic
  document.addEventListener('dailyPlanStepComplete', function(e) {
    // Debounce: ignore if already shown in last 3 seconds
    var now = Date.now();
    if (now - lastShownAt < 3000) return;
    lastShownAt = now;

    var headers = {};
    var jwtToken = localStorage.getItem('jwt_token');
    if (jwtToken) {
      headers['Authorization'] = 'Bearer ' + jwtToken;
    }

    fetch('/api/daily-plan/next-step', {
      credentials: 'same-origin',
      headers: headers
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        // Legacy banner (backward compatibility) — only if container exists
        if (container) {
          if (data.has_next) {
            container.innerHTML =
              '<a href="' + escapeHtml(data.step_url) + '" class="daily-next-banner">' +
                '<span class="daily-next-banner__icon">' + escapeHtml(data.step_icon) + '</span>' +
                '<span class="daily-next-banner__text">' +
                  '\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433: ' + escapeHtml(data.step_title) +
                  '<div class="daily-next-banner__progress">' + escapeHtml(data.steps_done) + ' \u0438\u0437 ' + escapeHtml(data.steps_total) + ' \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e</div>' +
                '</span>' +
                '<span class="daily-next-banner__arrow">\u2192</span>' +
              '</a>';
          } else if (data.all_done) {
            container.innerHTML =
              '<a href="/dashboard" class="daily-next-banner daily-next-banner--done">' +
                '<span class="daily-next-banner__icon">\u2728</span>' +
                '<span class="daily-next-banner__text">' +
                  '\u041f\u043b\u0430\u043d \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!' +
                  '<div class="daily-next-banner__progress">' + escapeHtml(data.steps_done) + ' \u0438\u0437 ' + escapeHtml(data.steps_total) + ' \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e</div>' +
                '</span>' +
              '</a>';
          }
        }

        // Modal overlay with auto-redirect
        if (modalShown) return;
        modalShown = true;
        showCompletionModal(data);
      })
      .catch(function(err) {
        console.error('Daily plan next step error:', err);
      });
  });

  function showCompletionModal(data) {
    var overlay = document.createElement('div');
    overlay.className = 'dp-modal-overlay';

    var countdownSeconds = 5;
    var countdownTimer = null;

    if (data.all_done) {
      overlay.innerHTML =
        '<div class="dp-modal">' +
          '<div class="dp-modal__icon">\uD83C\uDF89</div>' +
          '<div class="dp-modal__title">\u041f\u043b\u0430\u043d \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!</div>' +
          '<div class="dp-modal__countdown">' + escapeHtml(data.steps_done) + ' \u0438\u0437 ' + escapeHtml(data.steps_total) + ' \u0448\u0430\u0433\u043e\u0432 \u0441\u0434\u0435\u043b\u0430\u043d\u043e</div>' +
          '<a href="/dashboard" class="dp-modal__btn dp-modal__btn--done">\uD83C\uDFE0 \u041d\u0430 \u0433\u043b\u0430\u0432\u043d\u0443\u044e</a>' +
          '<button class="dp-modal__cancel" id="dp-modal-cancel">\u041e\u0441\u0442\u0430\u0442\u044c\u0441\u044f \u043d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435</button>' +
        '</div>';
      document.body.appendChild(overlay);

      overlay.querySelector('#dp-modal-cancel').addEventListener('click', function() {
        overlay.remove();
        modalShown = false;
      });
      return;
    }

    if (!data.has_next) return;

    var dashboardUrl = document.querySelector('[data-dashboard-url]');
    var fallbackUrl = dashboardUrl ? dashboardUrl.getAttribute('data-dashboard-url') : '/dashboard';
    var nextUrl = data.step_url || fallbackUrl;

    var modalTitle = isMissionPlan ? '\u042d\u0442\u0430\u043f \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d!' : '\u0428\u0430\u0433 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!';
    var nextLabel = isMissionPlan ? '\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u044d\u0442\u0430\u043f' : '\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433';

    overlay.innerHTML =
      '<div class="dp-modal">' +
        '<div class="dp-modal__icon">\u2705</div>' +
        '<div class="dp-modal__title">' + escapeHtml(modalTitle) + '</div>' +
        '<div class="dp-modal__countdown" id="dp-modal-countdown">' + escapeHtml(nextLabel) + ' \u0447\u0435\u0440\u0435\u0437 ' + countdownSeconds + '...</div>' +
        '<a href="' + escapeHtml(nextUrl) + '" class="dp-modal__btn" id="dp-modal-go">\u2192 ' + escapeHtml(data.step_title) + '</a>' +
        '<button class="dp-modal__cancel" id="dp-modal-cancel">\u041e\u0441\u0442\u0430\u0442\u044c\u0441\u044f \u043d\u0430 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435</button>' +
      '</div>';

    document.body.appendChild(overlay);

    // Countdown
    var countdownEl = document.getElementById('dp-modal-countdown');
    countdownTimer = setInterval(function() {
      countdownSeconds--;
      if (countdownSeconds <= 0) {
        clearInterval(countdownTimer);
        window.location.href = nextUrl;
        return;
      }
      countdownEl.textContent = nextLabel + ' \u0447\u0435\u0440\u0435\u0437 ' + countdownSeconds + '...';
    }, 1000);

    // Cancel button
    document.getElementById('dp-modal-cancel').addEventListener('click', function() {
      clearInterval(countdownTimer);
      overlay.remove();
      modalShown = false;
    });

    // Also update the sticky bar if it exists
    var bar = document.getElementById('daily-plan-bar');
    if (bar && bar.style.display !== 'none') {
      var dotsHtml = '';
      var total = data.steps_total || 0;
      var done = data.steps_done || 0;
      for (var i = 0; i < total; i++) {
        var cls = 'dp-bar__dot';
        if (i < done) cls += ' dp-bar__dot--done';
        else if (i === done) cls += ' dp-bar__dot--current';
        else cls += ' dp-bar__dot--upcoming';
        dotsHtml += '<span class="' + cls + '"></span>';
      }
      var dotsContainer = bar.querySelector('.dp-bar__progress');
      if (dotsContainer) dotsContainer.innerHTML = dotsHtml;

      var textEl = bar.querySelector('.dp-bar__text');
      var stepWord = isMissionPlan ? '\u042d\u0442\u0430\u043f' : '\u0428\u0430\u0433';
      if (textEl) textEl.textContent = stepWord + ' ' + (done + 1) + ' \u0438\u0437 ' + total;

      var btnEl = document.getElementById('dp-bar__next');
      if (btnEl) {
        btnEl.href = nextUrl;
        btnEl.textContent = '\u2192 ' + nextLabel;
      }
    }
  }
})();
