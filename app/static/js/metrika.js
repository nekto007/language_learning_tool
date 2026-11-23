/* Bounded funnel goals. No account ids, answers, form values or event params. */
(function () {
    'use strict';
    var element = document.getElementById('llt-metrika-config');
    if (!element || window.lltMetrikaGoal) return;
    var config;
    try { config = JSON.parse(element.textContent); } catch (_) { return; }
    if (!Number.isSafeInteger(config.id) || config.id <= 0) return;

    var allowed = new Set([
        'landing_preview_started', 'landing_preview_answered', 'landing_registration_click',
        'study_start_view', 'study_start_click', 'signup_completed',
        'learning_answered', 'lesson_completed'
    ]);
    var oncePerPage = new Set();
    window.ym = window.ym || function () {
        (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.l = window.ym.l || Date.now();
    window.lltMetrikaGoal = function (name) {
        if (!allowed.has(name)) return;
        // First checked answer on this page, including an incorrect answer.
        if (name === 'learning_answered') {
            if (oncePerPage.has(name)) return;
            oncePerPage.add(name);
        }
        try { window.ym(config.id, 'reachGoal', name); } catch (_) { /* optional analytics */ }
    };

    window.ym(config.id, 'init', config.options);
    var script = document.createElement('script');
    script.async = true;
    script.src = 'https://mc.yandex.ru/metrika/tag.js?id=' + config.id;
    if (element.nonce) script.nonce = element.nonce;
    document.head.appendChild(script);

    // Intent only; actual learning is reported from server grading below.
    document.addEventListener('DOMContentLoaded', function () {
        if (document.querySelector('[data-study-start]')) window.lltMetrikaGoal('study_start_view');
        // Defence in depth alongside the disabled field recording in Metrica.
        document.querySelectorAll('input, textarea').forEach(function (field) {
            field.classList.add('ym-disable-keys');
        });
    });
    document.addEventListener('click', function (event) {
        if (event.target.closest && event.target.closest('[data-study-start] .study-start__cta')) {
            window.lltMetrikaGoal('study_start_click');
        }
    });

    // Existing exercise scripts keep receiving the original Response, even if
    // analytics fails. We read only our server's allowlisted goal names.
    if (typeof window.fetch === 'function') {
        var originalFetch = window.fetch;
        window.fetch = function () {
            return originalFetch.apply(this, arguments).then(function (response) {
                try {
                    if (response.ok && new URL(response.url).origin === window.location.origin) {
                        (response.headers.get('X-LLT-Learning-Goals') || '').split(',').forEach(function (goal) {
                            window.lltMetrikaGoal(goal);
                        });
                    }
                } catch (_) { /* never affect grading or navigation */ }
                return response;
            });
        };
    }
}());
