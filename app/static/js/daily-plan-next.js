/**
 * Daily Plan Next Step Banner
 *
 * Shows a "next step" banner when user completes a daily plan activity.
 * Only activates when ?from=daily_plan is in the URL.
 */
(function() {
  'use strict';

  // Only activate if user came from daily plan
  var params = new URLSearchParams(window.location.search);
  if (params.get('from') !== 'daily_plan') return;

  // Find placeholder container
  var container = document.getElementById('daily-plan-next-step');
  if (!container) return;

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
    '.daily-next-banner__arrow{font-size:1.25rem;flex-shrink:0;opacity:.8;}';
  document.head.appendChild(style);

  // Listen for completion event from each page's own logic
  document.addEventListener('dailyPlanStepComplete', function() {
    fetch('/api/daily-plan/next-step', { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.has_next) {
          container.innerHTML =
            '<a href="' + data.step_url + '" class="daily-next-banner">' +
              '<span class="daily-next-banner__icon">' + data.step_icon + '</span>' +
              '<span class="daily-next-banner__text">' +
                '\u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439 \u0448\u0430\u0433: ' + data.step_title +
                '<div class="daily-next-banner__progress">' + data.steps_done + ' \u0438\u0437 ' + data.steps_total + ' \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e</div>' +
              '</span>' +
              '<span class="daily-next-banner__arrow">\u2192</span>' +
            '</a>';
        } else if (data.all_done) {
          container.innerHTML =
            '<a href="/dashboard" class="daily-next-banner daily-next-banner--done">' +
              '<span class="daily-next-banner__icon">\u2728</span>' +
              '<span class="daily-next-banner__text">' +
                '\u041f\u043b\u0430\u043d \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!' +
                '<div class="daily-next-banner__progress">' + data.steps_done + ' \u0438\u0437 ' + data.steps_total + ' \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043e</div>' +
              '</span>' +
            '</a>';
        }
      })
      .catch(function(err) {
        console.error('Daily plan next step error:', err);
      });
  });
})();
