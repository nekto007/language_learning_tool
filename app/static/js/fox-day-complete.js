/* The server confirms the study day. Refreshes never extend a series locally. */
(function () {
    'use strict';
    var card = document.querySelector('[data-fox-complete]');
    if (!card) return;
    var key = 'llt:fox-day:' + card.dataset.foxComplete;
    var seen = false;
    try { seen = localStorage.getItem(key) === '1'; } catch (_) { seen = true; }
    if (!seen) {
        try { localStorage.setItem(key, '1'); } catch (_) { /* static card still works */ }
        card.classList.add('fox-complete--animate');
        card.setAttribute('role', 'status');
    }
    card.querySelector('button').addEventListener('click', function () {
        card.classList.remove('fox-complete--animate');
        card.hidden = true;
        var route = document.querySelector('.learning-journey summary');
        if (route) route.focus();
    });
}());
