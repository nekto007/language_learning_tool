(() => {
  'use strict';

  const panel = document.querySelector('[data-quiz-choice-preview]');
  if (!panel) return;
  const view = window.LLTPracticeQuestionView;
  const form = document.getElementById('contentForm');
  const content = form.elements.namedItem('content');
  const open = document.querySelector('[data-quiz-choice-open]');
  const number = document.getElementById('quiz-choice-number');
  const check = document.getElementById('quiz-choice-check');
  const screen = document.getElementById('quiz-choice-screen');
  const result = document.getElementById('quiz-choice-result');
  const error = document.getElementById('quiz-choice-error');
  let displayed, selected, sequence = 0;

  const showError = (message, focus = false) => {
    error.textContent = message;
    error.hidden = !message;
    if (message && focus) error.focus();
  };

  const clear = () => {
    sequence += 1;
    displayed = null;
    selected = null;
    check.hidden = true;
    check.disabled = true;
    screen.replaceChildren();
    result.replaceChildren();
    showError('');
  };

  const current = () => ({content: content.value, question_number: number.valueAsNumber});

  const request = async body => {
    const response = await fetch(panel.dataset.quizChoicePreview, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': form.elements.namedItem('csrf_token').value,
      },
      body: JSON.stringify(body),
    });
    const received = await response.json().catch(() => null);
    if (!response.ok || !received) {
      throw new Error(received?.error || 'Не удалось загрузить предпросмотр. Повторите попытку.');
    }
    return received;
  };

  const load = async () => {
    clear();
    const started = sequence;
    const draft = current();
    try {
      const {question, support_mode: supportMode} = await request(draft);
      if (started !== sequence) return;
      displayed = draft;
      view.appendHeading(screen, question);
      if (question.context) {
        const context = document.createElement('p');
        context.textContent = question.context;
        screen.append(context);
      }
      view.appendTranslation(screen, question, supportMode);
      const options = document.createElement('div');
      options.className = 'my-3';
      view.appendChoices(options, question.options, {
        selected,
        disabled: false,
        onChange: value => {
          sequence += 1;
          selected = value;
          check.disabled = false;
          result.replaceChildren();
          showError('');
        },
      });
      screen.append(options);
      check.hidden = false;
    } catch (failure) {
      if (started === sequence) showError(failure.message, true);
    }
  };

  const changed = () => {
    if (panel.hidden) return;
    clear();
    showError('Обновите предпросмотр, чтобы увидеть текущий черновик.');
  };

  open.addEventListener('click', () => {
    panel.hidden = false;
    open.setAttribute('aria-expanded', 'true');
    document.getElementById('quiz-choice-title').focus();
    load();
  });
  document.getElementById('quiz-choice-load').addEventListener('click', load);
  document.getElementById('quiz-choice-close').addEventListener('click', () => {
    clear();
    panel.hidden = true;
    open.setAttribute('aria-expanded', 'false');
    content.focus();
  });
  content.addEventListener('input', changed);
  number.addEventListener('input', changed);
  check.addEventListener('click', async () => {
    if (!displayed || selected === null) return;
    const draft = current();
    if (draft.content !== displayed.content || draft.question_number !== displayed.question_number) {
      changed();
      return;
    }
    const started = ++sequence;
    const hadFocus = document.activeElement === check;
    check.disabled = true;
    result.replaceChildren();
    showError('');
    try {
      const {feedback} = await request({...displayed, answer: selected});
      if (started === sequence) result.append(view.feedbackBox(feedback, true));
    } catch (failure) {
      if (started === sequence) showError(failure.message, true);
    } finally {
      if (started === sequence) {
        check.disabled = false;
        if (hadFocus && document.activeElement === document.body) check.focus();
      }
    }
  });
})();
