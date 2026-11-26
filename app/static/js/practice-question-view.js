/* Presentation shared by the learner and the editor's one-question trial. */
(() => {
  'use strict';

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function appendHeading(parent, question) {
    parent.append(node('h2', question.instruction, 'h5'), node('p', question.prompt, 'fs-4 fw-bold'));
  }

  function appendTranslation(parent, question, mode) {
    if (!question.translation) return;
    if (mode === 'inline') parent.append(node('p', question.translation, 'text-secondary'));
    if (mode === 'toggle') {
      const details = node('details', null, 'my-2');
      details.append(node('summary', 'Показать перевод'), node('p', question.translation));
      parent.append(details);
    }
  }

  function appendChoices(parent, options, {selected, disabled, onChange}) {
    for (const option of options) {
      const label = node('label', null, 'card card-body mb-2');
      const field = node('input');
      field.type = 'radio';
      field.name = 'answer';
      field.value = option.value;
      field.checked = selected === option.value;
      field.disabled = disabled;
      field.addEventListener('change', () => onChange(option.value));
      label.append(field, document.createTextNode(' ' + option.label));
      parent.append(label);
    }
  }

  function feedbackBox(feedback, showExpected) {
    const box = node('div', null, feedback.correct ? 'alert alert-success' : 'alert alert-warning');
    box.setAttribute('role', 'status');
    box.append(node('h3', feedback.correct ? 'Верно' : 'Разберём ответ', 'h5'));
    if (!feedback.correct) {
      if (showExpected) box.append(node('p', 'Образец: ' + feedback.expected));
      box.append(node('p', feedback.explanation));
    }
    return box;
  }

  window.LLTPracticeQuestionView = {appendHeading, appendTranslation, appendChoices, feedbackBox};
})();
