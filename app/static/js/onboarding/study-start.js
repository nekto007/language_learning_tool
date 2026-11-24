// Measure exposure and intent separately from server-recorded lesson openings.
(function () {
  'use strict';
  var card = document.querySelector('[data-study-start]');
  if (!card || card.dataset.studyStartBound) return;
  card.dataset.studyStartBound = 'true';
  if (window.LLTPracticeDrafts && card.dataset.lesson && window.LLTPracticeDrafts.savedDraft(
      window, card.dataset.account, card.dataset.lesson, card.dataset.lessonType)) {
    card.dataset.resume = 'true';
    card.querySelector('.study-start__eyebrow').textContent = 'Продолжим занятие';
    card.querySelector('.study-start__cta').firstChild.textContent = 'Продолжить занятие ';
    card.querySelector('.study-start__note').textContent = 'Черновик этого занятия сохранён в этом браузере.';
  }
  function emit(name) {
    if (typeof window.gtag !== 'function') return;
    window.gtag('event', name, {
      level: card.dataset.level || '',
      lesson_type: card.dataset.lessonType || '',
      resumed: card.dataset.resume === 'true'
    });
  }
  emit('study_start_view');
  var button = card.querySelector('.study-start__cta');
  if (button) button.addEventListener('click', function () { emit('study_start_click'); });
})();
