/* Server-owned first attempt and assisted corrections. No answers are graded here. */
(() => {
  'use strict';
  const root = document.getElementById('guided-practice');
  if (!root) return;
  const screen = root.querySelector('#practice-screen');
  const errorBox = root.querySelector('#practice-error');
  const endpoint = root.dataset.endpoint;
  const activeKey = `llt:practice:${root.dataset.account}:${root.dataset.lesson}:active`;
  let lesson, state, busy = false, accountInvalid = false, storageKey, refreshButton;
  const node = (tag, text, css = '') => {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    el.className = css;
    return el;
  };
  const button = (text, action, primary = false) => {
    const el = node('button', text, primary ? 'btn btn-primary btn-lg my-2' : 'btn btn-outline-secondary btn-lg my-2');
    el.type = 'button'; el.disabled = busy;
    el.addEventListener('click', action); return el;
  };
  const blocks = (parent, rows) => (rows || []).forEach(row => {
    const box = node('article', null, 'card card-body my-3');
    if (row.title) box.append(node('h2', row.title, 'h5'));
    const body = node('p', row.body || '', 'mb-0'); body.style.whiteSpace = 'pre-wrap';
    box.append(body); parent.append(box);
  });
  const save = () => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state));
      sessionStorage.setItem(activeKey, storageKey);
    } catch (_) { /* Practice remains usable without storage. */ }
  };
  const perform = async action => {
    if (busy) return;
    busy = true; errorBox.hidden = true;
    root.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try { await action(); } catch (error) {
      if (['access_denied','authentication_required','csrf_error'].includes(error.code)) {
        lesson = null; state = null; accountInvalid = true; screen.replaceChildren();
      }
      errorBox.textContent = error.message; errorBox.hidden = false;
      errorBox.scrollIntoView({block: 'nearest'});
    } finally { busy = false; draw(); if (refreshButton) refreshButton.disabled = accountInvalid; }
  };
  const request = async (suffix = '', body) => {
    let response;
    try { response = await fetch(endpoint + suffix, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
      body: body ? JSON.stringify(body) : undefined
    }); } catch (_) { throw new Error('Связь прервалась. Ответы сохранены — попробуй ещё раз.'); }
    if (response.redirected || response.status === 401) {
      const error = new Error('Сессия завершилась. Войди в аккаунт заново.');
      error.code = 'authentication_required'; throw error;
    }
    let value;
    try { value = await response.json(); } catch (_) {
      const error = new Error(response.status === 400 ? 'Сессия изменилась. Открой план заново.'
        : 'Сервер временно недоступен. Ответы сохранены — попробуй ещё раз.');
      if (response.status === 400) error.code = 'authentication_required';
      throw error;
    }
    if (!response.ok || value.success === false) {
      const messages = {lesson_changed: 'Материал или попытка изменились. Открой актуальное задание.',
        lesson_locked: 'Сначала заверши предыдущий шаг плана.', invalid_input: 'Проверь, что ответ заполнен полностью.',
        access_denied: 'Аккаунт изменился. Открой план заново.', rate_limit_exceeded: 'Слишком много запросов. Попробуй немного позже.'};
      const error = new Error(messages[value.error] || 'Не удалось сохранить ответ. Попробуй ещё раз.');
      error.code = value.error; throw error;
    }
    return value;
  };
  const isCorrection = () => lesson.quiz_phase === 'correction';
  const display = (q, answer) => {
    if (q.input === 'choice') return q.options.find(o => o.value === answer)?.label || answer || '';
    if (q.input === 'order') {
      try { return JSON.parse(answer || '[]').map(v => q.options.find(o => o.value === v)?.label || '').join(' '); } catch (_) { return ''; }
    }
    if (q.input === 'match') {
      try { const pairs = JSON.parse(answer || '{}'); return (q.left_options || []).map(o => o.label + ' → ' + (q.options.find(r => r.value === pairs[o.value])?.label || '…')).join('\n'); } catch (_) { return ''; }
    }
    return answer || '';
  };
  const accepted = q => {
    const answer = state.answers[q.id] || '';
    const help = state.help[q.id] || q.correction_help;
    if (isCorrection() && help?.segments?.length) {
      const values = state.fragments[q.id] || help.segments.map(s => s.text);
      return help.segments.every((segment, index) => !segment.editable || (values[index] || '').trim());
    }
    try {
      if (q.input === 'order') return JSON.parse(answer).length === q.options.length;
      if (q.input === 'match') { const values = Object.values(JSON.parse(answer)); return values.length === q.options.length && new Set(values).size === values.length; }
    } catch (_) { return false; }
    return answer.trim().length > 0;
  };
  const audio = source => {
    if (!source) return;
    const player = node('audio'); player.controls = true; player.preload = 'metadata'; player.src = source;
    player.className = 'w-100 my-3'; screen.append(player);
  };
  const input = q => {
    const box = node('div', null, 'my-3');
    const checked = state.checks[q.id];
    const set = value => { state.answers[q.id] = value; save(); const check = screen.querySelector('[data-check]'); if (check) check.disabled = !accepted(q) || busy; };
    const help = state.help[q.id] || q.correction_help;
    if (isCorrection() && help?.segments?.length) {
      const values = help.segments.map(s => s.text);
      help.segments.forEach((segment, index) => {
        if (!segment.editable) { box.append(node('span', segment.text + ' ', 'me-1')); return; }
        const field = node('input'); field.type = 'text'; field.className = 'form-control d-inline-block my-1'; field.style.maxWidth = '12rem';
        field.setAttribute('aria-label', 'Пропущенное слово ' + (index + 1)); field.autocomplete = 'off'; field.disabled = !!checked;
        field.style.minHeight = '44px';
        field.value = (state.fragments[q.id] || values)[index] || '';
        field.addEventListener('input', () => { const next = [...(state.fragments[q.id] || values)]; next[index] = field.value; state.fragments[q.id] = next; set(next.join(' ')); });
        box.append(field);
      });
      if (help.choices?.length) box.append(node('p', 'Варианты: ' + help.choices.join(' · '), 'text-secondary mt-2'));
    } else if (q.input === 'choice') {
      q.options.forEach(option => {
        const label = node('label', null, 'card card-body mb-2');
        const field = node('input'); field.type = 'radio'; field.name = 'answer'; field.value = option.value;
        field.checked = state.answers[q.id] === option.value; field.disabled = !!checked;
        field.addEventListener('change', () => set(option.value));
        label.append(field, document.createTextNode(' ' + option.label)); box.append(label);
      });
    } else if (q.input === 'order') {
      let values; try { values = JSON.parse(state.answers[q.id] || '[]'); } catch (_) { values = []; }
      box.append(node('p', display(q, state.answers[q.id]) || 'Нажимай слова в правильном порядке.', 'fw-bold'));
      q.options.forEach(option => {
        const pick = button(option.label, () => { set(JSON.stringify([...values, option.value])); draw(); });
        pick.classList.add('me-2'); pick.disabled = !!checked || values.includes(option.value); box.append(pick);
      });
      if (!checked) box.append(button('Убрать последнее слово', () => { set(JSON.stringify(values.slice(0, -1))); draw(); }));
    } else if (q.input === 'match') {
      let values; try { values = JSON.parse(state.answers[q.id] || '{}'); } catch (_) { values = {}; }
      (q.left_options || []).forEach(left => {
        const label = node('label', left.label, 'd-block mb-3'); const select = node('select', null, 'form-select mt-2');
        select.style.minHeight = '44px';
        const empty = node('option', 'Выбери пару'); empty.value = ''; select.append(empty);
        q.options.forEach(right => { const option = node('option', right.label); option.value = right.value; select.append(option); });
        select.value = values[left.value] || ''; select.disabled = !!checked;
        select.addEventListener('change', () => { values[left.value] = select.value; if (!select.value) delete values[left.value]; set(JSON.stringify(values)); });
        label.append(select); box.append(label);
      });
    } else {
      const field = node('textarea', null, 'form-control'); field.rows = q.input === 'long_text' ? 8 : 2;
      field.setAttribute('aria-label', 'Твой ответ'); field.autocomplete = 'off'; field.spellcheck = false;
      field.value = state.answers[q.id] || ''; field.disabled = !!checked;
      field.addEventListener('input', () => set(field.value)); box.append(field);
    }
    screen.append(box);
  };
  const draw = () => {
    if (!lesson || !state) return;
    screen.replaceChildren();
    if (state.result) {
      const r = state.result, first = lesson.correction;
      screen.append(node('h2', r.correction_pending ? 'Первая попытка сохранена' : r.completed ? 'Занятие завершено' : 'Есть что повторить', 'h4'));
      if (r.score != null) screen.append(node('p', 'Результат первой попытки: ' + r.score + '%', 'fs-4 fw-bold'));
      const units = isCorrection() ? {correct: first.first_units_correct, total: first.first_units_total, label: first.first_unit_label}
        : {correct: r.units_correct, total: r.units_total, label: r.unit_label};
      if (units.total != null) screen.append(node('p', `${units.label}: ${units.correct} из ${units.total}`));
      if (isCorrection()) screen.append(node('p', `Исправлено: ${r.correct_count} из ${r.total_count}. Исходный результат ${first.first_score}% сохранён.`));
      if (r.correction_pending) screen.append(node('p', 'Продолжи план дня. Работа над ошибками появится отдельным шагом перед следующим связанным заданием.'));
      const link = node('a', 'К плану дня', 'btn btn-primary my-3'); link.href = root.querySelector('a').href; screen.append(link);
      if (!r.correction_pending && !isCorrection()) screen.append(button('Повторить урок', () => perform(async () => { try { sessionStorage.removeItem(storageKey); } catch (_) {} await load(true); })));
      (r.feedback || []).forEach(f => { const card = node('article', null, 'card card-body my-3'); card.append(node('h3', f.correct ? 'Верно' : 'Разберём ответ', 'h5'), node('p', f.prompt), node('p', 'Твой ответ: ' + f.answer)); if (!f.correct) card.append(node('p', 'Образец: ' + f.expected), node('p', f.explanation)); screen.append(card); });
      return;
    }
    if (isCorrection() && lesson.correction.theory_required && !state.theoryRead) {
      screen.append(node('h2', 'Повторим правило перед исправлениями', 'h4')); blocks(screen, lesson.theory);
      screen.append(button('Правило повторил — к исправлениям', () => { state.theoryRead = true; save(); draw(); }, true)); return;
    }
    if (state.intro) {
      screen.append(node('p', `Для зачёта — ${lesson.passing_score}%. Сначала ответь на все вопросы, затем отдельно разберём ошибки.`));
      if (lesson.instruction) screen.append(node('p', lesson.instruction)); audio(lesson.audio_url); blocks(screen, lesson.theory);
      screen.append(button('К заданиям', () => { state.intro = false; save(); draw(); }, true)); return;
    }
    if (state.index >= lesson.questions.length) {
      screen.append(node('h2', isCorrection() ? 'Сохраним исправления' : 'Первый круг завершён', 'h4'));
      lesson.questions.forEach(q => screen.append(node('p', q.prompt + '\n' + display(q, state.first[q.id] || state.answers[q.id]))));
      screen.append(button('Сохранить результат', () => perform(async () => {
        const answers = isCorrection() ? state.answers : state.first;
        // Keep the original nonce across timeouts and a full page reload.
        state.pendingSubmission ||= {session_token: lesson.session_token, answers};
        state.pendingLesson ||= lesson;
        save();
        try { state.result = await request('/submit', state.pendingSubmission); }
        catch (error) {
          if (['access_denied','authentication_required'].includes(error.code)) {
            lesson = null; state = null; screen.replaceChildren();
          }
          throw error;
        }
        delete state.pendingSubmission; delete state.pendingLesson;
        if (state.result.correction_pending || state.result.completed) { try { sessionStorage.removeItem(storageKey); } catch (_) {} }
        else save();
      }), true)); return;
    }
    const q = lesson.questions[state.index];
    const step = (lesson.learning_steps || []).find(s => s.question_ids.includes(q.id));
    if (step && !state.readSteps.includes(step.id)) {
      screen.append(node('h2', step.title, 'h4')); blocks(screen, step.theory);
      screen.append(button('Правило понятно — к практике', () => { state.readSteps.push(step.id); save(); draw(); }, true)); return;
    }
    screen.append(node('p', `${isCorrection() ? 'Исправление' : 'Вопрос'} ${state.index + 1} из ${lesson.questions.length}`, 'text-secondary'));
    screen.append(node('h2', q.instruction, 'h5'), node('p', q.prompt, 'fs-4 fw-bold'));
    if (q.context) screen.append(node('p', q.context)); audio(q.audio_url || lesson.audio_url);
    if (q.image_url) { const img = node('img'); img.src = q.image_url; img.alt = 'Иллюстрация к заданию'; img.className = 'img-fluid my-3'; screen.append(img); }
    if (q.video_url || lesson.video_url) { const video = node('video'); video.controls = true; video.src = q.video_url || lesson.video_url; video.className = 'w-100 my-3'; screen.append(video); }
    if (q.translation && lesson.support_mode === 'inline') screen.append(node('p', q.translation, 'text-secondary'));
    if (q.translation && lesson.support_mode === 'toggle') {
      const translation = node('details', null, 'my-2'); translation.append(node('summary', 'Показать перевод'), node('p', q.translation)); screen.append(translation);
    }
    if (['reading','text','listening_immersion_quiz'].includes(lesson.type) && lesson.theory?.length) {
      const reference = node('details', null, 'my-3'); reference.append(node('summary', 'Текст урока')); blocks(reference, lesson.theory); screen.append(reference);
    }
    const helpBlocks = q.theory_help?.length ? q.theory_help : lesson.theory;
    if (['inline', 'toggle'].includes(lesson.support_mode) && helpBlocks?.length) {
      const details = node('details', null, 'my-3'); details.append(node('summary', 'Правило к заданию')); blocks(details, helpBlocks); screen.append(details);
    }
    const help = state.help[q.id] || q.correction_help;
    if (help?.hint) screen.append(node('p', help.hint, 'text-secondary'));
    input(q);
    const feedback = state.checks[q.id];
    if (feedback) {
      const box = node('div', null, feedback.correct ? 'alert alert-success' : 'alert alert-warning');
      box.append(node('h3', feedback.correct ? 'Верно' : 'Разберём ответ', 'h5'));
      if (!feedback.correct) { if (!isCorrection()) box.append(node('p', 'Образец: ' + feedback.expected)); box.append(node('p', feedback.explanation)); }
      screen.append(box);
      if (isCorrection() && !feedback.correct) {
        screen.append(button('Попробовать ещё раз', () => { delete state.checks[q.id]; delete state.fragments[q.id]; if (help?.segments?.length) state.answers[q.id] = help.segments.map(s => s.text).join(' '); save(); draw(); }, true));
      } else screen.append(button('Дальше', () => { state.index += 1; save(); draw(); screen.scrollIntoView({block: 'start'}); }, true));
      // Keep the next action above the site's fixed mobile navigation.
      const action = screen.lastElementChild;
      action.style.scrollMarginBottom = 'calc(6rem + env(safe-area-inset-bottom))';
      action.scrollIntoView({block: 'nearest'});
    } else {
      const check = button('Проверить ответ', () => perform(async () => {
        const body = {session_token: lesson.session_token, question_id: q.id, answer: state.answers[q.id]};
        if (isCorrection()) body.help_level = Math.min(3, (state.levels[q.id] || 0) + 1);
        const response = await request('/check', body); const f = response.feedback;
        state.checks[q.id] = f;
        if (!(q.id in state.first)) state.first[q.id] = state.answers[q.id];
        if (f.correction_help) state.help[q.id] = f.correction_help;
        if (isCorrection() && !f.correct) state.levels[q.id] = Math.min(3, (state.levels[q.id] || 0) + 1);
        save();
      }), true);
      check.dataset.check = 'true'; check.disabled = busy || !accepted(q); screen.append(check);
    }
  };
  const load = async (fresh = false) => {
    if (!fresh) {
      let key, pending;
      try { key = sessionStorage.getItem(activeKey); pending = JSON.parse(sessionStorage.getItem(key)); } catch (_) {}
      if (pending?.pendingSubmission && pending.pendingLesson) {
        lesson = pending.pendingLesson; state = pending; storageKey = key;
        try {
          state.result = await request('/submit', state.pendingSubmission);
          delete state.pendingSubmission; delete state.pendingLesson;
          try { sessionStorage.removeItem(storageKey); } catch (_) {}
          draw(); return;
        } catch (error) {
          if (error.code === 'lesson_changed') {
            // A changed authored revision cannot reuse checked answers. Keep
            // the old draft separately and let Refresh open the current copy.
            try {
              sessionStorage.setItem(storageKey + ':expired:' + Date.now(), JSON.stringify(state));
              sessionStorage.removeItem(storageKey); sessionStorage.removeItem(activeKey);
            } catch (_) {}
          } else {
            if (['access_denied','authentication_required'].includes(error.code)) {
              lesson = null; state = null; screen.replaceChildren();
            }
            throw error;
          }
        }
      }
    }
    const document = await request();
    if (String(document.account_id) !== root.dataset.account) {
      const error = new Error('Аккаунт изменился. Открой план заново.');
      error.code = 'access_denied'; throw error;
    }
    lesson = document.lesson;
    storageKey = `llt:practice:${root.dataset.account}:${root.dataset.lesson}:${lesson.correction?.attempt_id || 'first'}`;
    const revision = lesson.content_revision || JSON.stringify(lesson.questions);
    let draft; try { draft = JSON.parse(sessionStorage.getItem(storageKey)); } catch (_) {}
    state = !fresh && draft?.revision === revision && !draft.result ? draft : {
      revision, index: 0, answers: {...(lesson.correction?.previous_answers || {})}, first: {}, checks: {},
      help: {}, fragments: {}, levels: {}, readSteps: [], theoryRead: false,
      intro: !isCorrection() && !(lesson.learning_steps || []).length
    };
    save(); draw();
  };
  refreshButton = button('Обновить задание', () => perform(() => load()));
  root.prepend(refreshButton);
  perform(() => load());
})();
