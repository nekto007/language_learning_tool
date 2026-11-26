/* Server-owned first attempt and assisted corrections. No answers are graded here. */
(() => {
  'use strict';
  const root = document.getElementById('guided-practice');
  if (!root) return;
  const screen = root.querySelector('#practice-screen');
  const errorBox = root.querySelector('#practice-error');
  const storageWarning = root.querySelector('#practice-storage-warning');
  const endpoint = root.dataset.endpoint;
  const readingPreview = root.dataset.readingPreview === 'true';
  const coursePractice = root.dataset.coursePractice === 'true';
  const drafts = !readingPreview && window.LLTPracticeDrafts ? new window.LLTPracticeDrafts.Store(window, root.dataset.account, root.dataset.lesson) : null;
  const draftStorage = () => drafts || window.sessionStorage;
  const lessonKey = `llt:practice:${root.dataset.account}:${root.dataset.lesson}:`;
  const draftPrefix = coursePractice ? lessonKey + 'course:' : lessonKey;
  const activeKey = draftPrefix + 'active';
  let lesson, state, busy = false, accountInvalid = false, storageKey, refreshButton, focusAfterDraw = false;
  let browserDraftAvailable = true, storageReadable = true, unloadGuarded = false;
  let resultPlan, resultActions;
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
  const warnBeforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
  const updateStorageWarning = () => {
    const warn = !browserDraftAvailable && state && !state.result && !accountInvalid;
    const note = root.querySelector('#practice-draft-note');
    if (note) {
      note.hidden = Boolean(state?.result || accountInvalid);
      note.textContent = warn ? 'Текущие изменения остаются только в этой вкладке.' : drafts?.durable
        ? coursePractice
          ? 'Черновик сохраняется в этом браузере. Чтобы продолжить, снова открой урок в модуле.'
          : 'Черновик сохраняется в этом браузере. Можно закрыть вкладку и продолжить через план дня.'
        : 'Черновик сохраняется только в этой вкладке. Чтобы продолжить позже, оставь её открытой.';
    }
    if (storageWarning) {
      storageWarning.hidden = !warn;
      storageWarning.textContent = state?.pendingSubmission
        ? 'Результат мог сохраниться на сервере. Черновик не записан в браузере. Не закрывай вкладку; повтори отправку здесь — будет использована та же попытка.'
        : 'Не удалось записать черновик в браузере. Ответы остаются в этой вкладке; не закрывай и не обновляй её до завершения.';
    }
    const dirty = warn && (state.pendingSubmission || Object.values(state.answers || {}).some(value => String(value).trim())
      || Object.values(state.previousRevision?.answers || {}).some(value => String(value).trim()));
    if (dirty && !unloadGuarded) { window.addEventListener('beforeunload', warnBeforeUnload); unloadGuarded = true; }
    else if (!dirty && unloadGuarded) { window.removeEventListener('beforeunload', warnBeforeUnload); unloadGuarded = false; }
  };
  const stored = key => {
    if (readingPreview) return null;
    try { const value = draftStorage().getItem(key); storageReadable = true; return value; }
    catch (_) { storageReadable = false; browserDraftAvailable = false; updateStorageWarning(); return null; }
  };
  const save = () => {
    if (readingPreview) return;
    try {
      draftStorage().setItem(storageKey, JSON.stringify(state));
      draftStorage().setItem(activeKey, storageKey);
      browserDraftAvailable = storageReadable;
    } catch (_) { browserDraftAvailable = false; }
    updateStorageWarning();
  };
  const retryNotice = () => !state || !Object.keys(state.answers || {}).length ? 'Попробуй ещё раз.'
    : browserDraftAvailable ? 'Ответы сохранены — попробуй ещё раз.' : 'Ответы остались в этой вкладке. Не закрывай её и попробуй ещё раз.';
  const perform = async action => {
    if (busy) return;
    focusAfterDraw = screen.contains(document.activeElement);
    busy = true; errorBox.hidden = true;
    screen.setAttribute('aria-busy', 'true');
    root.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try { await action(); } catch (error) {
      if (['access_denied','authentication_required','csrf_error'].includes(error.code)) {
        lesson = null; state = null; accountInvalid = true; screen.replaceChildren();
      }
      if (!lesson && error.code === 'lesson_locked') screen.querySelector('[data-practice-loading]')?.remove();
      errorBox.textContent = error.message; errorBox.hidden = false;
      errorBox.scrollIntoView({block: 'nearest'});
    } finally {
      busy = false; screen.setAttribute('aria-busy', 'false'); draw();
      if (state?.result) screen.scrollIntoView({block: 'start', behavior: 'instant'});
      if (refreshButton) refreshButton.disabled = accountInvalid;
    }
  };
  const fetchJson = async (url, body, signal) => {
    let response;
    try { response = await fetch(url, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin', signal,
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
      body: body ? JSON.stringify(body) : undefined
    }); } catch (_) { throw new Error('Связь прервалась. ' + retryNotice()); }
    if (response.redirected || response.status === 401) {
      const error = new Error('Сессия завершилась. Войди в аккаунт заново.');
      error.code = 'authentication_required'; throw error;
    }
    let value;
    try { value = await response.json(); } catch (_) {
      const error = new Error(response.status === 400 ? 'Сессия изменилась. Открой план заново.'
        : 'Сервер временно недоступен. ' + retryNotice());
      if (response.status === 400) error.code = 'authentication_required';
      throw error;
    }
    if (!response.ok || value.success === false) {
      const messages = {lesson_changed: 'Материал или попытка изменились. Открой актуальное задание.',
        lesson_locked: coursePractice
          ? 'Этот урок пока недоступен. Проверь предыдущие уроки и условия доступа в модуле.'
          : 'Сначала заверши предыдущий шаг плана.',
        invalid_input: 'Проверь, что ответ заполнен полностью.',
        plan_paused: 'План на паузе. Вернись к плану дня, чтобы продолжить.',
        authentication_required: 'Сессия завершилась. Войди в аккаунт заново.',
        unsupported_lesson: 'Материал пока недоступен. Вернись к плану дня или попробуй открыть задание позже.',
        access_denied: 'Аккаунт изменился. Открой план заново.', rate_limit_exceeded: 'Слишком много запросов. Попробуй немного позже.'};
      const error = new Error(messages[value.error] || 'Не удалось сохранить ответ. Попробуй ещё раз.');
      error.code = value.error; throw error;
    }
    return value;
  };
  const request = (suffix = '', body, signal) => fetchJson(endpoint + suffix, body, signal);
  const isCorrection = () => lesson.quiz_phase === 'correction';
  const isFinal = () => lesson.type === 'final_test';
  const completedResult = result => result?.completed === true
    || (result?.completed == null && result?.passed === true && result?.total_count === 0);
  const canContinueFrom = result => Boolean(root.dataset.resultPlan && lesson?.study_day && root.dataset.reviewOnly !== 'true'
    && (completedResult(result) || result?.correction_pending === true));
  const historyResultKey = 'lltPracticeResult';
  const readHistoryResult = () => window.history?.state?.[historyResultKey];
  const replaceHistoryResult = result => {
    try {
      const entry = {...window.history.state};
      if (result) entry[historyResultKey] = result;
      else delete entry[historyResultKey];
      window.history.replaceState(entry, '');
    } catch (_) {} // A rejected history write leaves the live result intact.
  };
  const resultFields = (source, fields) => Object.fromEntries(
    fields.filter(key => Object.hasOwn(source, key)).map(key => [key, source[key]])
  );
  const rememberResult = result => {
    if (!(canContinueFrom(result) || (coursePractice && (completedResult(result) || result?.correction_pending)))
        || result.success !== true || String(result.lesson_id) !== root.dataset.lesson
        || !lesson.content_revision || (isCorrection() && !completedResult(result))) return;
    replaceHistoryResult({
      account: root.dataset.account, lesson: root.dataset.lesson, coursePractice,
      revision: lesson.content_revision, type: lesson.type,
      studyDay: lesson.study_day, phase: lesson.quiz_phase,
      correction: resultFields(lesson.correction || {}, ['first_score', 'first_units_correct', 'first_units_total', 'first_unit_label']),
      result: resultFields(result, [
        'score', 'passed', 'completed', 'correction_pending', 'correct_count', 'total_count',
        'units_correct', 'units_total', 'unit_label'
      ])
    });
  };
  const restoreHistoryResult = async () => {
    const saved = readHistoryResult();
    if (!saved) return false;
    if (saved.account !== root.dataset.account || saved.lesson !== root.dataset.lesson || !saved.revision
        || Boolean(saved.coursePractice) !== coursePractice
        || !(completedResult(saved.result) || saved.result?.correction_pending === true)) {
      replaceHistoryResult(null);
      return false;
    }
    const identity = await request('?result_identity=1');
    if (String(identity.account_id) !== root.dataset.account) {
      const error = new Error('Аккаунт изменился. Открой план заново.');
      error.code = 'access_denied'; throw error;
    }
    const current = identity.lesson;
    if (String(current?.id) !== saved.lesson || current?.content_revision !== saved.revision || current?.type !== saved.type) {
      replaceHistoryResult(null); lesson = null; state = null;
      return false;
    }
    if (state?.result) await updateResultPlan(true);
    else {
      lesson = {...current, quiz_phase: saved.phase, correction: saved.correction, study_day: saved.studyDay};
      state = {result: saved.result};
    }
    return true;
  };
  const renderResultActions = () => {
    if (!resultActions || !state?.result) return;
    if (coursePractice) {
      resultActions.replaceChildren();
      if (completedResult(state.result) && root.dataset.courseNext) {
        const next = node('a', 'Следующий урок', 'btn btn-primary me-2');
        next.href = root.dataset.courseNext;
        resultActions.append(next);
      }
      const back = node('a', 'К урокам модуля', 'btn btn-outline-secondary');
      back.href = root.querySelector('a').href;
      resultActions.append(back);
      return;
    }
    const plan = resultPlan?.result === state.result ? resultPlan : {};
    const showNext = plan.status === 'next' && typeof plan.title === 'string' && plan.title.trim()
      && typeof plan.url === 'string' && plan.url.startsWith('/') && !plan.url.startsWith('//')
      && !plan.url.includes('\\');
    const focused = resultActions.contains(document.activeElement);
    resultActions.replaceChildren();
    const copy = {
      loading: 'Уточняем следующий шаг плана…',
      secured: 'План на сегодня выполнен. Можно отдохнуть.',
      paused: 'План на паузе. Чтобы продолжить, открой план дня.',
      day_changed: 'Начался новый учебный день. Открой актуальный план.',
      unavailable: 'Не удалось обновить план. Следующий шаг можно посмотреть в плане дня.'
    };
    if (showNext) resultActions.append(node('p', 'Следующее задание по плану', 'mb-1'));
    else if (copy[plan.status]) resultActions.append(node('p', copy[plan.status], 'mb-1'));
    const controls = node('div', null, 'd-flex flex-wrap gap-2 my-3');
    if (showNext) {
      const next = node('a', plan.title, 'btn btn-primary');
      next.href = plan.url; controls.append(next);
    }
    const exit = node('a', 'К плану дня', showNext ? 'btn btn-outline-secondary' : 'btn btn-primary');
    exit.href = root.querySelector('a').href; controls.append(exit); resultActions.append(controls);
    if (focused) exit.focus({preventScroll: true});
  };
  const updateResultPlan = async (force = false) => {
    const result = state?.result;
    if (!canContinueFrom(result) || (!force && resultPlan?.result === result)) return;
    const lookup = {result, status: 'loading'};
    resultPlan = lookup;
    renderResultActions();
    const isCurrent = () => resultPlan === lookup && state?.result === result;
    try {
      const plan = await fetchJson(root.dataset.resultPlan + '?result_day=' + encodeURIComponent(lesson.study_day));
      if (!isCurrent()) return;
      if (String(plan.account_id) !== root.dataset.account) {
        const error = new Error('Аккаунт изменился. Открой план заново.');
        error.code = 'access_denied'; throw error;
      }
      if (plan.status === 'next' && String(plan.lesson_id) === root.dataset.lesson
          && (plan.quiz_phase !== 'correction' || result.correction_pending !== true)) {
        plan.status = 'plan';
      }
      Object.assign(lookup, {status: plan.status, title: plan.title, url: plan.url});
    } catch (error) {
      if (!isCurrent()) return;
      if (['access_denied', 'authentication_required'].includes(error.code)) {
        lesson = null; state = null; accountInvalid = true;
        screen.replaceChildren();
        errorBox.textContent = error.message; errorBox.hidden = false;
        if (refreshButton) refreshButton.disabled = true;
        return;
      }
      lookup.status = 'unavailable';
    }
    renderResultActions();
  };
  const dispute = (parent, q, feedback) => {
    if (feedback.correct || !['quiz', 'grammar'].includes(lesson.type) || root.dataset.reviewOnly === 'true') return;
    const answer = state.answers[q.id];
    if (typeof answer !== 'string' || !answer.trim()) return;
    const previous = state.disputes?.[q.id];
    const entry = previous?.answer === answer ? previous : null;
    const status = node('p', entry?.status === 'sent' ? 'Ответ передан на проверку'
      : entry?.status === 'pending' ? (busy ? 'Передаём ответ на проверку…' : 'Статус отправки неизвестен. Можно повторить запрос.')
      : entry?.status === 'failed' ? entry.message : '', 'small mb-2');
    status.setAttribute('role', 'status'); status.dataset.disputeStatus = 'true'; parent.append(status);
    if (entry?.status === 'sent') return;
    const send = button(entry ? 'Повторить запрос' : 'Мой ответ тоже верный', () => perform(async () => {
      const record = {answer, status: 'pending'};
      state.disputes ||= {}; state.disputes[q.id] = record;
      save(); draw();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await request('/dispute', {session_token: lesson.session_token, question_id: q.id, answer}, controller.signal);
        if (response.success !== true) throw new Error('Unconfirmed dispute');
        record.status = 'sent';
      } catch (error) {
        if (['access_denied', 'authentication_required', 'csrf_error'].includes(error.code)) throw error;
        record.status = 'failed';
        record.message = error.code === 'lesson_changed' ? 'Материал изменился. Обнови задание перед повторным запросом.'
          : 'Не удалось подтвердить отправку. Можно повторить запрос.';
      } finally { clearTimeout(timer); }
      save();
    }));
    send.dataset.dispute = 'true'; parent.append(send);
  };
  // Basic grammar and quiz documents can supply options without an input type.
  const isChoiceQuestion = q => q.input === 'choice' ||
    (q.input == null && Array.isArray(q.options) && q.options.length > 0);
  const orderValues = answer => {
    try { const ids = JSON.parse(answer || '[]'); return Array.isArray(ids) ? ids : []; }
    catch (_) { return []; }
  };
  const orderTiles = (q, ids) => ids.filter(id => id !== q.order_terminal?.value);
  const completeOrder = (q, ids) => {
    const tiles = orderTiles(q, ids);
    return tiles.length === q.options.length && new Set(tiles).size === tiles.length &&
      tiles.every(id => q.options.some(option => option.value === id)) &&
      ids.length - tiles.length <= 1;
  };
  const display = (q, answer) => {
    if (isChoiceQuestion(q)) return q.options.find(o => o.value === answer)?.label || answer || '';
    if (q.input === 'order') {
      const ids = orderValues(answer);
      const terminal = q.order_terminal;
      const word = id => q.options.find(option => option.value === id)?.label ||
        (id === terminal?.value ? terminal.label : '');
      if (terminal && ids.at(-1) === terminal.value) return ids.slice(0, -1).map(word).join(' ') + terminal.label;
      const assembled = ids.map(word).join(' ');
      return terminal && !ids.includes(terminal.value) && completeOrder(q, ids) ? assembled + terminal.label : assembled;
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
      if (q.input === 'order') return completeOrder(q, orderValues(answer));
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
    } else if (isChoiceQuestion(q)) {
      q.options.forEach(option => {
        const label = node('label', null, 'card card-body mb-2');
        const field = node('input'); field.type = 'radio'; field.name = 'answer'; field.value = option.value;
        field.checked = state.answers[q.id] === option.value; field.disabled = !!checked;
        field.addEventListener('change', () => set(option.value));
        label.append(field, document.createTextNode(' ' + option.label)); box.append(label);
      });
    } else if (q.input === 'order') {
      const values = orderTiles(q, orderValues(state.answers[q.id]));
      box.append(node('p', display(q, state.answers[q.id]) || 'Нажимай слова в правильном порядке.', 'fw-bold'));
      q.options.forEach(option => {
        const pick = button(option.label, () => {
          set(JSON.stringify([...values, option.value]));
          draw();
          if (q.order_terminal && !isFinal()) {
            const check = screen.querySelector('[data-check]:enabled');
            if (check) {
              check.style.scrollMarginBottom = 'calc(6rem + env(safe-area-inset-bottom))';
              check.scrollIntoView({block: 'nearest'});
            }
          }
        });
        pick.classList.add('me-2');
        pick.disabled = !!checked || values.includes(option.value);
        box.append(pick);
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
  const drawContent = () => {
    if (!lesson || !state) return;
    resultActions = null;
    screen.replaceChildren();
    if (state.result) {
      const r = state.result, first = lesson.correction;
      screen.append(node('h2', r.correction_pending ? 'Первая попытка сохранена'
        : completedResult(r) ? 'Занятие завершено' : 'Есть что повторить', 'h4'));
      if (r.score != null) screen.append(node('p', (isFinal() ? 'Результат теста: ' : 'Результат первой попытки: ') + r.score + '%', 'fs-4 fw-bold'));
      const units = isCorrection() ? {correct: first.first_units_correct, total: first.first_units_total, label: first.first_unit_label}
        : {correct: r.units_correct, total: r.units_total, label: r.unit_label};
      if (units.total != null) screen.append(node('p', `${units.label}: ${units.correct} из ${units.total}`));
      if (isCorrection()) screen.append(node('p', `Исправлено: ${r.correct_count} из ${r.total_count}. Исходный результат ${first.first_score}% сохранён.`));
      if (r.correction_pending) screen.append(node('p', 'Работа над ошибками назначена отдельным заданием.'));
      resultActions = node('div', null, 'practice-result-actions');
      screen.append(resultActions);
      renderResultActions();
      updateResultPlan();
      if (!r.correction_pending && !isCorrection() && root.dataset.reviewOnly !== 'true') {
        screen.append(button('Повторить урок', () => perform(async () => {
          if (drafts && !await drafts.acquire()) throw new Error('Занятие открыто в другой вкладке.');
          replaceHistoryResult(null);
          try { draftStorage().removeItem(storageKey); } catch (_) {}
          await load(true);
        })));
      }
      (r.feedback || []).forEach(f => {
        const card = node('article', null, 'card card-body my-3');
        const answer = node('p', 'Твой ответ: ' + (f.answer_display || f.answer)); answer.style.whiteSpace = 'pre-wrap';
        card.append(node('h3', f.correct ? 'Верно' : 'Разберём ответ', 'h5'), node('p', f.prompt), answer);
        if (!f.correct) {
          const expected = node('p', 'Образец: ' + f.expected); expected.style.whiteSpace = 'pre-wrap';
          card.append(expected, node('p', f.explanation));
        }
        screen.append(card);
      });
      return;
    }
    if (isCorrection() && lesson.correction.theory_required && !state.theoryRead) {
      screen.append(node('h2', 'Повторим правило перед исправлениями', 'h4')); blocks(screen, lesson.theory);
      screen.append(button('Правило повторил — к исправлениям', () => { state.theoryRead = true; save(); draw(); }, true)); return;
    }
    if (state.intro) {
      screen.append(node('p', isFinal()
        ? `Для зачёта — ${lesson.passing_score}%. Ответь на все вопросы. Ответы можно изменить до отправки. Результат и разбор появятся после завершения теста.`
        : `Для зачёта — ${lesson.passing_score}%. Ответь на все вопросы. После проверки каждого ответа можно идти дальше. Результат — по первым ответам.`));
      if (lesson.instruction) screen.append(node('p', lesson.instruction)); audio(lesson.audio_url);
      if (!isFinal()) blocks(screen, lesson.theory);
      screen.append(button(isFinal() ? 'Начать тест' : 'К заданиям', () => { state.intro = false; save(); draw(); }, true)); return;
    }
    if (state.index >= lesson.questions.length) {
      if (readingPreview) {
        const correct = Object.values(state.checks).filter(result => result.correct).length;
        screen.append(node('h2', 'Предпросмотр завершён', 'h4'),
          node('p', `Верных ответов: ${correct} из ${lesson.questions.length}`),
          button('Начать сначала', () => perform(() => load(true)), true));
        return;
      }
      screen.append(node('h2', isFinal() ? 'Проверь ответы перед отправкой' : isCorrection() ? 'Сохраним исправления' : 'Первый круг завершён', 'h4'));
      if (state.pendingSubmission) screen.append(node('p', 'Отправка начата. Пока результат не подтверждён, повторяем ту же попытку без изменения ответов.'));
      lesson.questions.forEach((q, index) => {
        const row = node('article', null, 'card card-body my-3');
        const answer = node('p', q.prompt + '\n' + display(q, isFinal() ? state.answers[q.id] : state.first[q.id] || state.answers[q.id]));
        answer.style.whiteSpace = 'pre-wrap'; row.append(answer);
        if (isFinal() && !state.pendingSubmission) row.append(button('Изменить ответ ' + (index + 1), () => { state.index = index; save(); draw(); }));
        screen.append(row);
      });
      screen.append(button('Сохранить результат', () => perform(async () => {
        const answers = isCorrection() || isFinal() ? state.answers : state.first;
        // Keep the original nonce across timeouts and a full page reload.
        state.pendingSubmission ||= {session_token: lesson.session_token, answers: {...answers}};
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
        rememberResult(state.result);
        if (state.result.correction_pending || state.result.completed) { try { draftStorage().removeItem(storageKey); } catch (_) {} }
        else save();
      }), true)); return;
    }
    const q = lesson.questions[state.index];
    const step = !isFinal() && (lesson.learning_steps || []).find(s => s.question_ids.includes(q.id));
    if (step && !state.readSteps.includes(step.id)) {
      screen.append(node('h2', step.title, 'h4')); blocks(screen, step.theory);
      screen.append(button('Правило понятно — к практике', () => { state.readSteps.push(step.id); save(); draw(); }, true)); return;
    }
    screen.append(node('p', `${isCorrection() ? 'Исправление' : 'Вопрос'} ${state.index + 1} из ${lesson.questions.length}`, 'text-secondary'));
    screen.append(node('h2', q.instruction, 'h5'), node('p', q.prompt, 'fs-4 fw-bold'));
    if (q.context) screen.append(node('p', q.context)); audio(q.audio_url || lesson.audio_url);
    if (q.image_url) { const img = node('img'); img.src = q.image_url; img.alt = 'Иллюстрация к заданию'; img.className = 'img-fluid my-3'; screen.append(img); }
    if (q.video_url || lesson.video_url) { const video = node('video'); video.controls = true; video.src = q.video_url || lesson.video_url; video.className = 'w-100 my-3'; screen.append(video); }
    if (!isFinal() && q.translation && lesson.support_mode === 'inline') screen.append(node('p', q.translation, 'text-secondary'));
    if (!isFinal() && q.translation && lesson.support_mode === 'toggle') {
      const translation = node('details', null, 'my-2'); translation.append(node('summary', 'Показать перевод'), node('p', q.translation)); screen.append(translation);
    }
    if (['reading','text','listening_immersion_quiz'].includes(lesson.type) && lesson.theory?.length) {
      const reference = node('details', null, 'my-3'); reference.append(node('summary', 'Текст урока')); blocks(reference, lesson.theory); screen.append(reference);
    }
    const helpBlocks = q.theory_help?.length ? q.theory_help : lesson.theory;
    if (!isFinal() && ['inline', 'toggle'].includes(lesson.support_mode) && helpBlocks?.length) {
      const details = node('details', null, 'my-3'); details.append(node('summary', 'Правило к заданию')); blocks(details, helpBlocks); screen.append(details);
    }
    const help = state.help[q.id] || q.correction_help;
    if (!isFinal() && help?.hint) screen.append(node('p', help.hint, 'text-secondary'));
    input(q);
    if (isFinal()) {
      const next = button(state.index === lesson.questions.length - 1 ? 'К проверке ответов' : 'Дальше', () => {
        state.index += 1; save(); draw(); screen.scrollIntoView({block: 'start'});
      }, true);
      next.dataset.check = 'true'; next.disabled = busy || !accepted(q); screen.append(next);
      if (state.index > 0) screen.append(button('Предыдущий вопрос', () => { state.index -= 1; save(); draw(); }));
      return;
    }
    const feedback = state.checks[q.id];
    if (feedback) {
      const box = node('div', null, feedback.correct ? 'alert alert-success' : 'alert alert-warning');
      box.setAttribute('role', 'status');
      box.append(node('h3', feedback.correct ? 'Верно' : 'Разберём ответ', 'h5'));
      if (!feedback.correct) { if (!isCorrection()) box.append(node('p', 'Образец: ' + feedback.expected)); box.append(node('p', feedback.explanation)); }
      dispute(box, q, feedback);
      screen.append(box);
      if ((isCorrection() || root.dataset.reviewOnly === 'true') && !feedback.correct) {
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
  const draw = () => {
    const restoreFocus = focusAfterDraw || screen.contains(document.activeElement);
    drawContent(); focusAfterDraw = false;
    updateStorageWarning();
    if (lesson && state?.previousRevision && !accountInvalid) {
      const previous = state.previousRevision;
      const details = node('details', null, 'card card-body my-3');
      details.append(node('summary', 'Предыдущие ответы к обновлённому материалу'));
      details.append(node('p', 'Материал изменился. Эти ответы сохранены отдельно и не отправляются в новой попытке.'));
      Object.entries(previous.answers || {}).forEach(([id, answer]) => {
        const question = (previous.questions || []).find(q => q.id === id);
        const text = node('p', (question?.prompt || 'Ответ ' + id) + '\n' + (question ? display(question, answer) : answer));
        text.style.whiteSpace = 'pre-wrap'; details.append(text);
      });
      screen.append(details);
    }
    if (restoreFocus) {
      const target = !errorBox.hidden ? errorBox : screen.querySelector('[role="status"] h3') || screen.querySelector('h2') || screen.firstElementChild;
      if (target) { target.tabIndex = -1; target.focus({preventScroll: true}); }
    }
  };
  const load = async (fresh = false) => {
    let expiredDraft;
    const memoryDraft = state;
    if (!fresh) {
      // If storage is blocked, the in-memory outbox still owns the original
      // nonce. Refresh must retry it before asking for another document.
      let key = storageKey, pending = state?.pendingSubmission ? state : null;
      if (!pending) { key = stored(activeKey); try { pending = JSON.parse(stored(key)); } catch (_) {} }
      if (pending?.pendingSubmission && pending.pendingLesson) {
        lesson = pending.pendingLesson; state = pending; storageKey = key;
        try {
          state.result = await request('/submit', state.pendingSubmission);
          delete state.pendingSubmission; delete state.pendingLesson;
          rememberResult(state.result);
          try { draftStorage().removeItem(storageKey); } catch (_) {}
          draw(); return;
        } catch (error) {
          if (error.code === 'lesson_changed') {
            expiredDraft = pending;
            // A changed authored revision cannot reuse checked answers. Keep
            // the old draft separately and let Refresh open the current copy.
            try {
              draftStorage().setItem(storageKey + ':expired:' + Date.now(), JSON.stringify(state));
              draftStorage().removeItem(storageKey); draftStorage().removeItem(activeKey);
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
    const document = root.dataset.startId
      ? await request('/start', {item_id: root.dataset.startId, request_id: root.dataset.requestId})
      : await request(coursePractice ? '?mode=course' : '');
    if (String(document.account_id) !== root.dataset.account) {
      const error = new Error('Аккаунт изменился. Открой план заново.');
      error.code = 'access_denied'; throw error;
    }
    lesson = document.lesson;
    const goal = root.querySelector('#practice-goal');
    if (goal) { goal.textContent = lesson.learning_goal ? 'Цель: ' + lesson.learning_goal : ''; goal.hidden = !lesson.learning_goal; }
    const attempt = lesson.correction?.attempt_id || 'first';
    storageKey = draftPrefix + attempt;
    const revision = lesson.content_revision || JSON.stringify(lesson.questions);
    let draft; try { draft = JSON.parse(stored(storageKey)); } catch (_) {}
    if (!draft && !fresh && coursePractice) {
      // Pre-upgrade browser drafts came from the plan-gated editor. Copy
      // input, but replay any signed pending submission only in that mode.
      let previous; try { previous = JSON.parse(stored(lessonKey + attempt)); } catch (_) {}
      if (!previous?.pendingSubmission) draft = previous;
    }
    if (!draft && !fresh && !browserDraftAvailable && !expiredDraft) draft = memoryDraft;
    const compatibleDraft = draft?.revision === revision && (!draft.lessonType || draft.lessonType === lesson.type)
      // This editor did not previously support finals. An untyped legacy
      // draft cannot be carried into an assessment without feedback.
      && (!isFinal() || draft.lessonType === 'final_test');
    const previous = expiredDraft || (!fresh && draft && !compatibleDraft ? draft : null);
    if (previous && !expiredDraft) {
      try { draftStorage().setItem(storageKey + ':expired:' + Date.now(), JSON.stringify(previous)); } catch (_) { browserDraftAvailable = false; }
    }
    state = !fresh && !expiredDraft && compatibleDraft && !draft.result ? draft : {
      revision, lessonType: lesson.type, index: 0, answers: {...(isFinal() && !fresh ? lesson.resume_answers : lesson.correction?.previous_answers || {})}, first: {}, checks: {},
      help: {}, fragments: {}, levels: {}, readSteps: [], theoryRead: false,
      intro: !isCorrection() && (isFinal() || !(lesson.learning_steps || []).length),
      previousRevision: previous ? {questions: previous.draftQuestions || [], answers: {...previous.answers}}
        : !fresh ? draft?.previousRevision : undefined
    };
    state.lessonType = lesson.type;
    state.draftQuestions ||= lesson.questions.map(q => ({id: q.id, input: q.input, prompt: q.prompt, options: q.options, left_options: q.left_options}));
    if (isFinal() && !draft && !fresh && lesson.resume_answers && Object.keys(lesson.resume_answers).length) {
      const firstOpen = lesson.questions.findIndex(q => !state.answers[q.id]);
      state.index = firstOpen < 0 ? lesson.questions.length : firstOpen; state.intro = false;
    }
    save(); draw();
  };
  refreshButton = button('Обновить задание', () => openEditor());
  root.prepend(refreshButton);
  let opening = false;
  const openEditor = async (fromHistory = false) => {
    if (opening || accountInvalid || busy) return;
    if (fromHistory && state?.result && !readHistoryResult()) { await updateResultPlan(true); return; }
    opening = true;
    let keepEditorLocked = false;
    try {
      await perform(async () => {
        if (await restoreHistoryResult()) return;
        if (drafts && !await drafts.acquire()) {
          lesson = null; state = null; screen.replaceChildren();
          screen.append(node('h2', 'Занятие открыто в другой вкладке', 'h4'));
          screen.append(node('p', 'Продолжи там или закрой ту вкладку, затем нажми «Продолжить здесь». Это защищает ответы от перезаписи.'));
          screen.append(button('Продолжить здесь', () => openEditor(), true));
          keepEditorLocked = true;
          return;
        }
        await load();
      });
    } finally {
      opening = false;
      if (keepEditorLocked) {
        refreshButton.disabled = true;
        screen.querySelector('button').disabled = false;
      }
    }
  };
  window.addEventListener('pagehide', () => { if (drafts) drafts.close(); });
  window.addEventListener('pageshow', event => { if (event.persisted) openEditor(true); });
  window.addEventListener('focus', () => { if (state?.result) updateResultPlan(true); });
  openEditor();
})();
