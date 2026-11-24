let currentIndex = 0;
let correctCount = 0;
let wrongCount = 0;
let totalXP = 0;

// Abort a hung /submit so the button never stays disabled forever.
const SUBMIT_TIMEOUT_MS = 15000;
let exerciseGeneration = 0;
let activeDispute = null;
let checkedAnswer = null;

function isCurrentExercise(generation, exerciseId, practiceSession) {
  return generation === exerciseGeneration && String(sessionId) === practiceSession
    && String(exercises[currentIndex]?.id) === exerciseId;
}

function clearDispute() {
  exerciseGeneration++;
  if (activeDispute?.controller) activeDispute.controller.abort();
  activeDispute = null;
  const btn = document.getElementById('dispute-btn');
  const status = document.getElementById('dispute-status');
  if (btn) { btn.style.display = 'none'; btn.disabled = false; btn.textContent = 'Мой ответ тоже верный'; }
  if (status) { status.style.display = 'none'; status.textContent = ''; }
}

function renderDispute(record) {
  if (record !== activeDispute) return;
  if (!isCurrentExercise(record.generation, record.exerciseId, record.practiceSession)) { clearDispute(); return; }
  const btn = document.getElementById('dispute-btn');
  const status = document.getElementById('dispute-status');
  if (!btn || !status) return;
  status.textContent = record.status === 'sent' ? 'Ответ передан на проверку'
    : record.status === 'pending' ? 'Передаём ответ на проверку…'
    : record.status === 'unavailable' ? 'Задание или сессия изменились. Обновите страницу для проверки ответа.'
    : record.status === 'failed' ? 'Не удалось подтвердить отправку. Можно повторить запрос.' : '';
  status.style.display = status.textContent ? 'block' : 'none';
  btn.style.display = ['sent', 'unavailable'].includes(record.status) ? 'none' : 'inline-flex';
  btn.disabled = record.status === 'pending';
  btn.textContent = record.status === 'failed' ? 'Повторить запрос' : 'Мой ответ тоже верный';
}

const disputeButton = document.getElementById('dispute-btn');
if (disputeButton) disputeButton.addEventListener('click', async function() {
  const record = activeDispute;
  if (!record) return;
  if (!isCurrentExercise(record.generation, record.exerciseId, record.practiceSession)) { clearDispute(); return; }
  if (['pending', 'sent', 'unavailable'].includes(record.status)) return;
  record.status = 'pending';
  const controller = new AbortController(); record.controller = controller;
  const timeout = setTimeout(() => controller.abort(), SUBMIT_TIMEOUT_MS);
  renderDispute(record);
  try {
    const response = await fetch(`/grammar-lab/api/exercise/${record.exerciseId}/dispute`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken()},
      body: JSON.stringify({dispute_token: record.token, answer: record.answer}), signal: controller.signal
    });
    if (record !== activeDispute || !isCurrentExercise(record.generation, record.exerciseId, record.practiceSession)) return;
    if (response.redirected || [401, 403, 409].includes(response.status)) { record.status = 'unavailable'; return; }
    if (!response.ok || (await response.json()).success !== true) throw new Error('Unconfirmed dispute');
    if (record === activeDispute && isCurrentExercise(record.generation, record.exerciseId, record.practiceSession)) {
      record.status = 'sent';
      checkedAnswer.reported = true;
      saveSessionState();
    }
  } catch (_) {
    if (record === activeDispute && isCurrentExercise(record.generation, record.exerciseId, record.practiceSession)) record.status = 'failed';
  } finally {
    clearTimeout(timeout); record.controller = null; renderDispute(record);
  }
});
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('pagehide', event => {
    // A cached page can receive the grade for its pending submit when it resumes.
    if (!event.persisted || activeDispute) clearDispute();
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted && checkedAnswer) showExercise(currentIndex);
  });
}

// Pristine «Проверить» button markup, captured before any submit mutates it.
// showExercise() restores this for every exercise so a previous submit's
// disabled / «Проверка…»-spinner state never leaks into the next exercise.
const CHECK_BTN_HTML = (document.getElementById('check-btn') || {}).innerHTML || 'Проверить';

// An exercise is renderable only if it carries the content its type needs to
// be answered. Broken module-imported items (e.g. a fill_blank whose
// "question" is just an instruction with no blank, sentence or options) would
// otherwise render an empty input with nothing to do. We drop them up front so
// the user only ever sees actionable exercises.
function isRenderable(ex) {
  if (!ex || typeof ex !== 'object') return false;
  const t = (ex.exercise_type || '').toLowerCase();
  const txt = (v) => (v == null ? '' : String(v)).trim();
  if (t === 'reorder') return Array.isArray(ex.words) && ex.words.length > 0;
  if (t === 'multiple_choice') return Array.isArray(ex.options) && ex.options.length >= 2;
  if (t === 'matching') {
    const p = ex.pairs || (ex.content && ex.content.pairs) || [];
    return Array.isArray(p) && p.length > 0;
  }
  if (t === 'true_false') return !!txt(ex.statement || ex.question);
  if (t === 'error_correction') return !!txt(ex.sentence || ex.question);
  if (t === 'fill_blank') {
    // Needs a blank to fill (question with ___) or an explicit source sentence.
    return txt(ex.question).indexOf('___') !== -1 || !!txt(ex.sentence);
  }
  // translation / transformation / default: need a non-empty prompt phrase.
  return !!txt(ex.question || ex.sentence || ex.statement || ex.original);
}

// Drop unactionable exercises from the server-provided set before anything
// uses ``exercises`` (progress counts, session cache, rendering).
exercises = (exercises || []).filter(isRenderable);

// Get CSRF token safely
function getCSRFToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

const practiceActor = document.querySelector('meta[name="llt-account-id"]')?.content;
const sessionKey = practiceActor ? `grammar_practice:${practiceActor}:${topicId || 'srs'}` : null;

function saveSessionState() {
  if (!sessionKey) return;
  try {
    const revisions = Object.fromEntries(exercises.map(ex => [ex.id, exerciseRevisions[ex.id]]));
    sessionStorage.setItem(sessionKey, JSON.stringify({
      exercises, revisions, sessionId, currentIndex, correctCount, wrongCount, totalXP, checkedAnswer,
      timestamp: Date.now()
    }));
  } catch (_) {
    // Storage can be unavailable or full; a confirmed grade is still final in this tab.
  }
}

function clearSessionState() {
  if (sessionKey) {
    try { sessionStorage.removeItem(sessionKey); } catch (_) { /* Storage is optional. */ }
  }
}

function restoreSession() {
  if (!sessionKey) return;
  try {
    const state = JSON.parse(sessionStorage.getItem(sessionKey));
    if (!state) return;
    const items = state.exercises;
    const index = state.currentIndex;
    // Topic practice resamples on reload. Validate against all current topic revisions.
    // For a mixed review, only the exercises still available in today's selection can resume.
    const fresh = Array.isArray(items) && items.every(ex => isRenderable(ex)
      && typeof exerciseRevisions[ex.id] === 'string' && exerciseRevisions[ex.id] === state.revisions?.[ex.id]);
    const result = state.checkedAnswer;
    const validResult = result == null || (typeof result.correct === 'boolean' && result.exerciseId === items?.[index]?.id
      && typeof result.given === 'string' && typeof result.expected === 'string');
    if (!fresh || !validResult || typeof state.sessionId !== 'string' || !state.sessionId || state.sessionId.length > 100
        || !Number.isFinite(state.timestamp) || Date.now() - state.timestamp > 3600000
        || !Number.isInteger(index) || index < 0 || index >= items.length
        || ![state.correctCount, state.wrongCount, state.totalXP].every(n => Number.isInteger(n) && n >= 0)
        || state.correctCount + state.wrongCount !== index + (result ? 1 : 0)) {
      clearSessionState();
      return;
    }
    exercises = items;
    sessionId = state.sessionId;
    currentIndex = index;
    correctCount = state.correctCount;
    wrongCount = state.wrongCount;
    totalXP = state.totalXP;
    checkedAnswer = result;
  } catch (_) {
    clearSessionState();
    return;
  }
  document.getElementById('start-screen').style.display = 'none';
  document.getElementById('exercise-screen').style.display = 'block';
  showExercise(currentIndex);
}

// Try to restore session on page load
document.addEventListener('DOMContentLoaded', function() {
  restoreSession();
});

// Start button
document.getElementById('start-btn').addEventListener('click', function() {
  if (!exercises.length) {
    // Every server-provided exercise was unactionable — nothing to practise.
    const start = document.getElementById('start-screen');
    const desc = start && start.querySelector('.practice-start__desc');
    if (desc) desc.textContent = 'Нет корректных упражнений для этой темы.';
    const btn = document.getElementById('start-btn');
    if (btn) btn.disabled = true;
    return;
  }
  document.getElementById('start-screen').style.display = 'none';
  document.getElementById('exercise-screen').style.display = 'block';
  saveSessionState();
  showExercise(0);
});

function showExercise(index) {
  const exercise = exercises[index];
  if (!exercise) return;
  clearDispute();

  // Update progress
  const answeredCount = correctCount + wrongCount;
  document.getElementById('progress-text').textContent = `${answeredCount} / ${exercises.length}`;
  document.getElementById('progress-bar').style.width = `${(answeredCount / exercises.length) * 100}%`;

  // Set topic badge with link to topic
  const topicBadge = document.getElementById('topic-badge');
  // Topic practice already names the topic in its heading. Mixed practice names each exercise's topic here.
  topicBadge.hidden = Boolean(topicId || !exercise.topic_title);
  topicBadge.textContent = exercise.topic_title || '';
  if (exercise.topic_id) {
    topicBadge.href = '/grammar-lab/topic/' + exercise.topic_id;
    topicBadge.classList.add('practice-exercise__topic--linked');
  } else {
    topicBadge.removeAttribute('href');
    topicBadge.classList.remove('practice-exercise__topic--linked');
  }

  if (checkedAnswer) {
    showCheckedExercise(exercise, checkedAnswer);
    return;
  }

  // Render question
  const questionArea = document.getElementById('question-area');
  questionArea.innerHTML = renderExercise(exercise);

  // Reset UI — fully restore the check button to a clean, clickable state.
  // The submit handler leaves it disabled and showing the «Проверка…» spinner
  // (it only hides it on success); without this reset the next exercise would
  // inherit that stuck state and the button would be a frozen spinner.
  document.getElementById('feedback-area').style.display = 'none';
  const _checkBtn = document.getElementById('check-btn');
  _checkBtn.disabled = false;
  _checkBtn.innerHTML = CHECK_BTN_HTML;
  _checkBtn.style.opacity = '';
  _checkBtn.style.display = 'inline-flex';
  document.getElementById('next-btn').style.display = 'none';

  // Setup handlers
  setupExerciseHandlers(exercise);
}

function answerText(exercise, answer) {
  if (exercise.exercise_type === 'matching') {
    const pairs = exercise.pairs || exercise.content?.pairs || [];
    const isKey = Array.isArray(answer);
    return pairs.map((pair, i) => {
      const left = isKey ? answer[i] : pair;
      const right = isKey ? answer[i] : pairs[answer?.[i]];
      const source = left?.english || left?.left;
      const target = right?.russian || right?.right;
      return source && target ? `${source} → ${target}` : '';
    }).filter(Boolean).join('\n');
  }
  if (exercise.exercise_type === 'true_false') {
    return {true: 'Верно', false: 'Неверно'}[String(answer).toLowerCase()] || '';
  }
  return String(answer ?? '');
}

function checkedExercise(exercise, data, submitted) {
  const xp = Number.isSafeInteger(data.xp_earned) && data.xp_earned > 0 ? data.xp_earned : 0;
  return {
    exerciseId: exercise.id, correct: data.is_correct, xp,
    given: answerText(exercise, data.user_answer ?? submitted),
    expected: answerText(exercise, data.correct_answer),
    explanation: typeof data.explanation === 'string' ? data.explanation.trim() : '',
    token: typeof data.dispute_token === 'string' ? data.dispute_token.trim() : '',
    submitted, reported: false
  };
}

function showCheckedExercise(exercise, result) {
  const question = document.getElementById('question-area');
  question.replaceChildren();
  const prompt = [exercise.instruction, exercise.question, exercise.sentence, exercise.statement, exercise.original];
  for (const line of new Set(prompt.filter(Boolean))) {
    const text = document.createElement('p');
    text.textContent = line;
    question.append(text);
  }
  const answer = document.createElement('p');
  answer.className = 'practice-exercise__submitted';
  answer.textContent = 'Ваш ответ: ' + result.given;
  question.append(answer);

  const feedback = document.getElementById('feedback-area');
  feedback.replaceChildren();
  feedback.className = 'practice-exercise__feedback ' + (result.correct ? 'success' : 'error');
  const heading = document.createElement('strong');
  heading.className = 'practice-exercise__feedback-header';
  heading.textContent = result.correct ? (result.xp ? `Правильно! +${result.xp} XP` : 'Правильно!') : 'Неверно';
  feedback.append(heading);
  if (!result.correct && result.expected) {
    const key = document.createElement('span');
    key.className = 'practice-exercise__feedback-answer';
    key.textContent = result.expected;
    feedback.append('Правильный ответ: ', key);
  }
  if (!result.correct && result.explanation) {
    const explanation = document.createElement('p');
    explanation.className = 'practice-exercise__explanation';
    explanation.textContent = result.explanation;
    feedback.append(explanation);
  }
  feedback.style.display = 'block';
  document.getElementById('check-btn').style.display = 'none';
  document.getElementById('next-btn').style.display = 'inline-flex';
  document.getElementById('next-label').textContent = currentIndex + 1 === exercises.length ? 'Посмотреть результат' : 'Далее';
  if (!result.correct && result.token) {
    activeDispute = {generation: exerciseGeneration, exerciseId: String(exercise.id), practiceSession: String(sessionId),
                     token: result.token, answer: result.submitted, status: result.reported ? 'sent' : 'idle'};
    renderDispute(activeDispute);
  }
}

function renderExercise(exercise) {
  // Data comes directly from exercise, NOT from exercise.content
  const question = exercise.question || exercise.instruction || '';
  const options = exercise.options || [];
  // Separate authored constraints must stay visible alongside the source phrase.
  const escapeInstruction = value => String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
  const instructionText = exercise.instruction ? escapeInstruction(exercise.instruction) : '';
  const instructionHtml = instructionText && exercise.question
    ? `<p class="practice-instruction">${instructionText}</p>` : '';
  const statement = exercise.statement || exercise.question || '';
  const sentence = exercise.sentence || exercise.question || '';
  const exerciseType = (exercise.exercise_type || '').toLowerCase();

  // A source-phrase block (sentence / statement / original) the user
  // is supposed to act on. Rendered for fill_blank/default whenever
  // the exercise carries a non-empty phrase but no dedicated case
  // handles it — without this, exercises authored as
  // ``{question: "Что означает эта фраза?", sentence: "I am happy"}``
  // would render only the question with nothing to translate.
  const sourcePhrase = (exercise.sentence || exercise.statement || exercise.original || '').toString().trim();
  const sourcePhraseHtml = sourcePhrase
    ? `<p style="font-size: 1.125rem; font-weight: 600; color: var(--grammar-text); margin: 0.5rem 0 1rem; padding: 1rem; background: var(--grammar-surface-alt); border-radius: 8px;">${sourcePhrase}</p>`
    : '';

  switch (exerciseType) {
    case 'fill_blank':
      return `
        ${instructionHtml}
        <label>${question || 'Заполните пропуск:'}</label>
        ${sourcePhraseHtml}
        <input type="text" id="user-answer" placeholder="Введите ответ" autocomplete="off">
      `;

    case 'multiple_choice': {
      let html = `${instructionHtml}<label>${question || 'Выберите правильный ответ:'}</label>`;
      // Options are shown in a random order (the authored files put the
      // key in position 2 in 40 of 48 items — a positional cue), but the
      // value sent to the server stays the ORIGINAL index: the grader
      // compares indexes against content.options as authored.
      const order = options.map((_, i) => i);
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
      order.forEach((origIndex) => {
        html += `
          <label class="practice-option" data-action="select-option" data-value="${origIndex}">
            <input type="radio" name="answer" value="${origIndex}">
            <span class="practice-option__radio"></span>
            <span class="practice-option__text">${options[origIndex]}</span>
          </label>
        `;
      });
      return html;
    }

    case 'true_false':
      return `
        ${instructionText ? `<p class="practice-instruction">${instructionText}</p>` : ''}
        <label>${statement}</label>
        <div class="practice-tf">
          <button type="button" class="practice-tf__btn practice-tf__btn--true" data-action="select-tf" data-value="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 6L9 17l-5-5"/>
            </svg>
            Верно
          </button>
          <button type="button" class="practice-tf__btn practice-tf__btn--false" data-action="select-tf" data-value="false">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
            Неверно
          </button>
        </div>
        <input type="hidden" id="user-answer" value="">
      `;

    case 'translation': {
      // Translation supports both directions (ru→en and en→ru). The
      // exercise model exposes ``source_lang`` / ``target_lang`` so we
      // pick the right prompt label and always show the source phrase.
      // Earlier code hardcoded "Переведите на английский:" AND stripped
      // that prefix from sentence, so en→ru exercises (where
      // ``question`` reads "Что означает эта фраза?" and the English
      // phrase lives in ``sentence``) rendered as just the question
      // with no phrase to translate.
      //
      // ``question`` is used as label only when it differs from the
      // source phrase — otherwise (e.g. question="Откуда ты?",
      // sentence="Откуда ты?") it would duplicate the phrase below.
      const targetLang = (exercise.target_lang || 'en').toString().toLowerCase();
      const isToRussian = targetLang === 'ru' || targetLang === 'rus' || targetLang === 'russian';
      const defaultLabel = isToRussian ? 'Переведите на русский:' : 'Переведите на английский:';
      const translationText = (sentence || '').replace(/^Переведите на (английский|русский):\s*/i, '').trim();
      const questionIsPhrase = !!question && question.trim() === translationText;
      const labelText = instructionText || ((question && !questionIsPhrase) ? question : defaultLabel);
      const placeholderText = isToRussian ? 'Ваш перевод (на русский)' : 'Ваш перевод';
      const phraseHtml = translationText
        ? `<p style="font-size: 1.125rem; font-weight: 600; color: var(--grammar-text); margin: 0.5rem 0 1rem; padding: 1rem; background: var(--grammar-surface-alt); border-radius: 8px;">${translationText}</p>`
        : '';
      return `
        <label>${labelText}</label>
        ${phraseHtml}
        <input type="text" id="user-answer" placeholder="${placeholderText}" autocomplete="off">
      `;
    }

    case 'reorder':
      return renderReorder(exercise);

    case 'matching':
      return renderMatching(exercise);

    case 'error_correction':
      return `
        <label>${instructionText || 'Найдите и исправьте ошибку:'}</label>
        <p style="font-size: 1.125rem; font-weight: 600; color: var(--grammar-text); margin: 0.5rem 0 1rem; padding: 1rem; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px;">${sentence}</p>
        <input type="text" id="user-answer" placeholder="Исправленное слово/фраза" autocomplete="off">
      `;

    case 'transformation':
      const original = exercise.original || sentence;
      const instruction = exercise.instruction || 'Преобразуйте предложение';
      return `
        <label>${instruction}:</label>
        <p style="font-size: 1.125rem; font-weight: 600; color: var(--grammar-text); margin: 0.5rem 0 1rem; padding: 1rem; background: var(--grammar-surface-alt); border-radius: 8px;">${original}</p>
        <input type="text" id="user-answer" placeholder="Введите преобразованное предложение" autocomplete="off">
      `;

    default:
      return `
        <label>${question || 'Введите ответ:'}</label>
        ${sourcePhraseHtml}
        <input type="text" id="user-answer" placeholder="Введите ответ" autocomplete="off">
      `;
  }
}

function selectOption(el, value) {
  document.querySelectorAll('.practice-option').forEach(opt => opt.classList.remove('selected'));
  el.classList.add('selected');
  el.querySelector('input').checked = true;
}

function selectTF(el, value) {
  document.querySelectorAll('.practice-tf__btn').forEach(btn => btn.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('user-answer').value = value;
}

// CSP-safe delegated handlers for dynamic exercise UI
document.addEventListener('click', function(e) {
  var optEl = e.target.closest('[data-action="select-option"]');
  if (optEl) {
    selectOption(optEl, parseInt(optEl.getAttribute('data-value'), 10));
    return;
  }
  var tfEl = e.target.closest('[data-action="select-tf"]');
  if (tfEl) {
    selectTF(tfEl, tfEl.getAttribute('data-value'));
  }
});

function renderReorder(exercise) {
  const words = exercise.words || [];
  const shuffledWords = [...words];
  for (let i = shuffledWords.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffledWords[i], shuffledWords[j]] = [shuffledWords[j], shuffledWords[i]];
  }

  let html = `<label>${exercise.instruction || 'Составьте предложение из слов:'}</label>`;
  html += '<div class="practice-wordbank" id="word-bank">';
  shuffledWords.forEach((word, i) => {
    html += `<button type="button" class="practice-word" data-index="${i}" data-word="${word}">${word}</button>`;
  });
  html += '</div>';
  html += '<div class="practice-answer-area empty" id="answer-area"><span class="practice-answer-placeholder">Нажмите на слова выше</span></div>';
  html += '<input type="hidden" id="user-answer" value="">';

  setTimeout(() => {
    const wordBank = document.getElementById('word-bank');
    const answerArea = document.getElementById('answer-area');
    const hiddenInput = document.getElementById('user-answer');
    // Store selected word indices (not just words, to handle duplicates)
    let selectedIndices = [];

    function updateAnswerArea() {
      if (selectedIndices.length > 0) {
        // Render clickable word buttons in answer area
        const wordButtons = selectedIndices.map((idx, pos) => {
          const word = wordBank.querySelector(`[data-index="${idx}"]`).dataset.word;
          return `<button type="button" class="practice-answer-word" data-pos="${pos}" data-index="${idx}">${word}</button>`;
        }).join('');
        answerArea.innerHTML = wordButtons;
        answerArea.classList.remove('empty');

        // Add click handlers to remove words from answer
        answerArea.querySelectorAll('.practice-answer-word').forEach(btn => {
          btn.addEventListener('click', function() {
            const idx = parseInt(this.dataset.index);
            const pos = parseInt(this.dataset.pos);
            // Remove from selectedIndices
            selectedIndices.splice(pos, 1);
            // Remove selected class from word bank
            wordBank.querySelector(`[data-index="${idx}"]`).classList.remove('selected');
            updateAnswerArea();
          });
        });
      } else {
        answerArea.innerHTML = '<span class="practice-answer-placeholder">Нажмите на слова выше</span>';
        answerArea.classList.add('empty');
      }
      // Update hidden input with joined words
      hiddenInput.value = selectedIndices.map(idx =>
        wordBank.querySelector(`[data-index="${idx}"]`).dataset.word
      ).join(' ');
    }

    wordBank?.querySelectorAll('.practice-word').forEach(btn => {
      btn.addEventListener('click', function() {
        const idx = parseInt(this.dataset.index);
        if (this.classList.contains('selected')) {
          // Remove from selection
          const pos = selectedIndices.indexOf(idx);
          if (pos > -1) selectedIndices.splice(pos, 1);
          this.classList.remove('selected');
        } else {
          // Add to selection
          selectedIndices.push(idx);
          this.classList.add('selected');
        }
        updateAnswerArea();
      });
    });
  }, 100);

  return html;
}

function renderMatching(exercise) {
  const pairs = exercise.pairs || exercise.content?.pairs || [];
  if (pairs.length === 0) {
    return `<label>Нет пар для сопоставления</label>`;
  }

  const rightItems = pairs.map((pair, i) => ({
    text: pair.russian || pair.right,
    correctIndex: i
  }));
  for (let i = rightItems.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [rightItems[i], rightItems[j]] = [rightItems[j], rightItems[i]];
  }

  let html = `<label>${exercise.instruction || 'Соотнесите пары:'}</label>`;
  html += '<div class="practice-matching">';
  html += '<div class="practice-matching__column" id="matching-left">';
  pairs.forEach((pair, i) => {
    html += `<div class="practice-matching__item" data-index="${i}" data-side="left">${pair.english || pair.left}</div>`;
  });
  html += '</div>';
  html += '<div class="practice-matching__column" id="matching-right">';
  rightItems.forEach((item, i) => {
    html += `<div class="practice-matching__item" data-index="${i}" data-correct="${item.correctIndex}" data-side="right">${item.text}</div>`;
  });
  html += '</div>';
  html += '</div>';
  html += `<div class="practice-matching__progress">Совпадений: <strong id="match-count">0</strong> из <strong>${pairs.length}</strong></div>`;
  html += '<input type="hidden" id="user-answer" value="">';

  setTimeout(() => setupMatchingHandlers(pairs.length), 100);

  return html;
}

function setupMatchingHandlers(totalPairs) {
  let selectedLeft = null;
  let selectedRight = null;
  let matches = {};
  let matchCount = 0;

  const leftItems = document.querySelectorAll('#matching-left .practice-matching__item');
  const rightItems = document.querySelectorAll('#matching-right .practice-matching__item');

  function updateAnswer() {
    document.getElementById('user-answer').value = JSON.stringify(matches);
    document.getElementById('match-count').textContent = matchCount;
  }

  function checkMatch() {
    if (selectedLeft !== null && selectedRight !== null) {
      const leftIdx = parseInt(selectedLeft.dataset.index);
      const rightCorrect = parseInt(selectedRight.dataset.correct);

      if (leftIdx === rightCorrect) {
        selectedLeft.classList.remove('selected');
        selectedLeft.classList.add('matched');
        selectedRight.classList.remove('selected');
        selectedRight.classList.add('matched');
        matches[leftIdx] = leftIdx;
        matchCount++;
        updateAnswer();
      } else {
        selectedLeft.classList.add('wrong');
        selectedRight.classList.add('wrong');
        setTimeout(() => {
          selectedLeft?.classList.remove('selected', 'wrong');
          selectedRight?.classList.remove('selected', 'wrong');
          selectedLeft = null;
          selectedRight = null;
        }, 500);
        return;
      }
      selectedLeft = null;
      selectedRight = null;
    }
  }

  leftItems.forEach(item => {
    item.addEventListener('click', function() {
      if (this.classList.contains('matched')) return;
      leftItems.forEach(i => i.classList.remove('selected'));
      this.classList.add('selected');
      selectedLeft = this;
      checkMatch();
    });
  });

  rightItems.forEach(item => {
    item.addEventListener('click', function() {
      if (this.classList.contains('matched')) return;
      rightItems.forEach(i => i.classList.remove('selected'));
      this.classList.add('selected');
      selectedRight = this;
      checkMatch();
    });
  });
}

function setupExerciseHandlers(exercise) {
  // Focus on input if exists
  const input = document.getElementById('user-answer');
  if (input && input.type === 'text') {
    input.focus();
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        const checkBtn = document.getElementById('check-btn');
        const nextBtn = document.getElementById('next-btn');
        if (checkBtn.style.display !== 'none') {
          checkBtn.click();
        } else if (nextBtn.style.display !== 'none') {
          nextBtn.click();
        }
      }
    });
  }
}

// Check answer
document.getElementById('check-btn').addEventListener('click', async function() {
  const exercise = exercises[currentIndex];
  const checkBtn = this;
  if (!exercise || checkedAnswer || checkBtn.disabled) return;
  const exerciseType = (exercise.exercise_type || '').toLowerCase();
  let answer;

  if (exerciseType === 'multiple_choice') {
    const selected = document.querySelector('input[name="answer"]:checked');
    if (!selected) {
      alert('Выберите ответ');
      return;
    }
    answer = selected.value;
  } else if (exerciseType === 'matching') {
    const answerStr = document.getElementById('user-answer').value;
    if (!answerStr) {
      alert('Соотнесите все пары');
      return;
    }
    try {
      const matches = JSON.parse(answerStr);
      const pairsCount = (exercise.pairs || exercise.content?.pairs || []).length;
      if (Object.keys(matches).length < pairsCount) {
        alert(`Соотнесите все пары (${Object.keys(matches).length}/${pairsCount})`);
        return;
      }
      answer = matches;
    } catch (e) {
      alert('Соотнесите все пары');
      return;
    }
  } else {
    answer = document.getElementById('user-answer').value;
    if (!answer) {
      alert('Введите ответ');
      return;
    }
  }

  // Show loading state on button
  const originalHTML = checkBtn.innerHTML;
  checkBtn.disabled = true;
  checkBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 0.8s linear infinite"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg> Проверка...`;
  checkBtn.style.opacity = '0.7';

  // Abort a hung request so the button can never stay stuck on «Проверка…».
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), SUBMIT_TIMEOUT_MS);
  const generation = exerciseGeneration, exerciseId = String(exercise.id), practiceSession = String(sessionId);
  const submittedAnswer = JSON.parse(JSON.stringify(answer));
  let answered = false;  // true only when the answer was graded & shown

  try {
    const response = await fetch(`/grammar-lab/api/exercise/${exercise.id}/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken()
      },
      body: JSON.stringify({
        answer: answer,
        session_id: sessionId,
        source: topicId ? 'topic_practice' : 'srs_review'
      }),
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error('submit failed: HTTP ' + response.status);
    }

    const data = await response.json();
    if (!isCurrentExercise(generation, exerciseId, practiceSession)) return;
    if (typeof data?.is_correct !== 'boolean') throw new Error('Invalid grade response');

    checkedAnswer = checkedExercise(exercise, data, submittedAnswer);
    if (checkedAnswer.correct) {
      correctCount++;
      totalXP += checkedAnswer.xp;
    } else {
      wrongCount++;
    }
    saveSessionState();
    showExercise(currentIndex);
    document.getElementById('next-btn').focus({preventScroll: true});
    answered = true;

  } catch (error) {
    if (!isCurrentExercise(generation, exerciseId, practiceSession)) return;
    console.error('grammar submit failed:', error);
    const feedback = document.getElementById('feedback-area');
    if (feedback) {
      feedback.className = 'practice-exercise__feedback error';
      feedback.textContent = (error && error.name === 'AbortError')
        ? 'Превышено время ожидания. Проверьте соединение и попробуйте снова.'
        : 'Ошибка при отправке ответа. Попробуйте снова.';
      feedback.style.display = 'block';
    }
  } finally {
    clearTimeout(timeoutId);
    // On any failure the button must return to a usable state — never leave it
    // disabled on «Проверка…» forever. On success it is hidden above instead.
    if (!answered && isCurrentExercise(generation, exerciseId, practiceSession)) {
      checkBtn.disabled = false;
      checkBtn.innerHTML = originalHTML;
      checkBtn.style.opacity = '';
    }
  }
});

// Next exercise
document.getElementById('next-btn').addEventListener('click', function() {
  if (!checkedAnswer) return;
  checkedAnswer = null;
  clearDispute();
  currentIndex++;
  if (currentIndex < exercises.length) {
    saveSessionState();
    showExercise(currentIndex);
  } else {
    // Complete - clear session state
    clearSessionState();
    document.getElementById('exercise-screen').style.display = 'none';
    document.getElementById('complete-screen').style.display = 'block';
    document.getElementById('correct-count').textContent = correctCount;
    document.getElementById('wrong-count').textContent = wrongCount;
    document.getElementById('xp-earned').textContent = totalXP;

    const accuracy = exercises.length > 0 ? Math.round((correctCount / exercises.length) * 100) : 0;
    document.getElementById('accuracy-fill').style.width = `${accuracy}%`;
    document.getElementById('accuracy-text').textContent = `${accuracy}%`;

    document.getElementById('progress-bar').style.width = '100%';
    document.getElementById('progress-text').textContent = `${exercises.length} / ${exercises.length}`;

  }
});
