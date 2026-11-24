(function () {
  'use strict';
  var root = document.getElementById('placement-root');
  if (!root) return;
  var base = root.dataset.api, account = root.dataset.account, guest = root.dataset.guest === 'true';
  var prefix = 'llt-placement-v1:' + account + ':';
  var statusNode = document.getElementById('placement-status');
  var chooser = document.getElementById('placement-chooser');
  var test = document.getElementById('placement-test');
  var result = document.getElementById('placement-result');
  var resume = document.getElementById('placement-resume');
  var retry = document.getElementById('placement-retry');
  var pause = document.getElementById('placement-pause');
  var change = document.getElementById('placement-change');
  var text = document.getElementById('placement-text');
  var audio = document.getElementById('placement-audio');
  var submit = document.getElementById('placement-answer');
  var unknown = document.getElementById('placement-unknown');
  var draftStatus = document.getElementById('placement-draft-status');
  var dialog = document.getElementById('placement-change-dialog');
  var current = null, latest = null, active = null, pending = read('pending');
  var busy = false, sequence = 0, draftTimer = null, nextMode = null, draftDurable = true;
  var messages = {
    bank_unavailable: 'Тест пока готовится. Можно начать обучение с выбранного вручную уровня.',
    bank_incomplete: 'Часть заданий временно недоступна. Попробуй продолжить позже.',
    active_attempt: 'У тебя уже есть начатый тест. Продолжи его или выбери другой вариант.',
    stale_question: 'Задание уже изменилось на другом устройстве. Обновим состояние.',
    answer_already_saved: 'Ответ уже сохранён на другом устройстве. Продолжим с текущего задания.',
    attempt_closed: 'Попытка уже завершена на другом устройстве. Обновим состояние теста.',
    newer_result_applied: 'Уже выбран уровень из более нового результата.',
    empty_answer: 'Введи ответ или нажми «Не знаю».',
    guest_expired: 'Срок гостевой попытки истёк. Обнови страницу, чтобы начать новый тест.',
    access_denied: 'Аккаунт изменился. Открой страницу снова.',
    not_found: 'Попытка недоступна для этого аккаунта.',
    invalid_option: 'Выбери один из предложенных вариантов.'
  };
  function read(key) {
    try { return JSON.parse(localStorage.getItem(prefix + key) || 'null'); } catch (_) { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(prefix + key, JSON.stringify(value)); return true; } catch (_) { return false; }
  }
  function remove(key) { try { localStorage.removeItem(prefix + key); } catch (_) {} }
  if (pending && (typeof pending.attempt !== 'string' || typeof pending.question_id !== 'string' ||
      typeof pending.answer !== 'string' || typeof pending.dont_know !== 'boolean')) pending = null;
  function say(value) { statusNode.textContent = value || ''; }
  function request(path, body) {
    var headers = {'Accept': 'application/json'};
    if (guest) headers['X-LLT-Placement-Guest'] = '1'; else headers['X-LLT-Account-ID'] = account;
    var options = {headers: headers, credentials: 'same-origin', cache: 'no-store'};
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
      options.method = 'POST'; options.body = JSON.stringify(body);
    }
    return fetch(base + path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.success !== true) {
          var error = new Error(messages[data.error] || 'Не получилось сохранить ответ. Попробуй снова.');
          error.code = data.error; error.status = response.status; throw error;
        }
        return data;
      });
    });
  }
  function selected() {
    if (!current || !current.question) return '';
    if (current.question.input === 'text') return text.value;
    var checked = document.querySelector('input[name="placement-option"]:checked');
    return checked ? checked.value : '';
  }
  function availability() {
    submit.disabled = busy || !!pending || !selected().trim(); unknown.disabled = busy || !!pending;
    text.disabled = busy || !!pending;
    document.querySelectorAll('input[name="placement-option"]').forEach(function (e) { e.disabled = busy || !!pending; });
    pause.disabled = busy || !!pending;
    change.disabled = busy || !!pending;
    root.setAttribute('aria-busy', String(busy));
  }
  function run(operation) {
    if (busy) return Promise.resolve();
    busy = true; var token = ++sequence; availability();
    document.querySelectorAll('[data-mode]').forEach(function (button) { button.disabled = true; });
    return operation().catch(function (error) {
      say(error.message || 'Нет связи. Попробуй ещё раз.');
      retry.hidden = !pending;
      if (error.code === 'stale_question' || error.code === 'answer_already_saved' || error.code === 'attempt_closed') {
        pending = null; remove('pending'); retry.hidden = true; return loadStatus(false);
      }
      if (pending && error.status && error.status < 500 && error.status !== 429 && error.status !== 401 && error.status !== 403) {
        pending = null; remove('pending'); retry.hidden = true;
      }
    }).finally(function () {
      if (token !== sequence) return;
      busy = false; availability();
      document.querySelectorAll('[data-mode]').forEach(function (button) { button.disabled = !root.dataset.available || !!pending; });
    });
  }
  function stopAudio() { audio.pause(); audio.removeAttribute('src'); audio.load(); }
  function localKey(attempt, question) { return 'draft:' + attempt + ':' + question; }
  function edit() {
    availability();
    if (!current || !current.question || busy || pending) return;
    var qid = current.question.id, id = current.id, value = selected();
    var local = write(localKey(id, qid), value);
    draftDurable = false; draftStatus.textContent = 'Сохраняем ответ…';
    clearTimeout(draftTimer);
    draftTimer = setTimeout(function () { saveDraft(id, qid, value, local); }, 500);
  }
  function saveDraft(id, qid, value, local) {
    return request('/' + encodeURIComponent(id) + '/draft', {question_id: qid, answer: value}).then(function () {
      if (current && current.id === id && current.question && current.question.id === qid && selected() === value) {
        draftDurable = true; draftStatus.textContent = 'Ответ сохранён. Можно продолжить позже.';
        remove(localKey(id, qid));
      }
    }).catch(function () {
      if (current && current.id === id && current.question && current.question.id === qid) {
        draftStatus.textContent = local ? 'Нет связи. Ответ сохранён на этом устройстве.' : 'Не удалось сохранить ответ. Оставь страницу открытой и попробуй снова.';
      }
      return false;
    });
  }
  function render(attempt, focus) {
    clearTimeout(draftTimer); stopAudio(); current = attempt; chooser.hidden = true;
    test.hidden = attempt.status !== 'active'; result.hidden = attempt.status !== 'completed';
    pause.hidden = attempt.status !== 'active'; retry.hidden = !pending;
    change.hidden = attempt.status !== 'active';
    if (attempt.status === 'completed') {
      var info = attempt.result;
      document.getElementById('placement-apply').hidden = guest;
      document.getElementById('placement-result-title').textContent = 'Рекомендуем начать с ' + info.recommended_level;
      document.getElementById('placement-result-summary').textContent = 'Верно: ' + info.correct_count + ' из ' + info.total + '. Выбор уровня не удалит пройденные уроки.';
      var list = document.getElementById('placement-domains'); list.replaceChildren();
      info.domains.forEach(function (domain) {
        var li = document.createElement('li'), strong = document.createElement('strong');
        strong.textContent = domain.title; li.appendChild(strong);
        li.appendChild(document.createTextNode(domain.total ? domain.correct + ' из ' + domain.total + ' заданий' : 'В этом варианте не проверялось'));
        list.appendChild(li);
      });
      var topics = document.getElementById('placement-topics-list'); topics.replaceChildren();
      (info.weak_topics || []).forEach(function (topic) { var li = document.createElement('li'); li.textContent = topic; topics.appendChild(li); });
      document.getElementById('placement-topics').hidden = !info.weak_topics.length;
      var apply = document.getElementById('placement-apply'); apply.textContent = 'Выбрать уровень ' + info.recommended_level;
      apply.disabled = attempt.applied;
      document.getElementById('placement-apply-status').textContent = attempt.applied ?
        (info.effective_on ? 'Уровень выбран. Новые планы будут учитывать его с ' + info.effective_on + '. Сегодняшний план сохраняется.' : 'Уровень выбран. Можно перейти к обучению.') : '';
      if (focus) document.getElementById('placement-result-title').focus();
      return;
    }
    if (attempt.status !== 'active') return;
    var question = attempt.question;
    document.getElementById('placement-counter').textContent = 'Задание ' + (attempt.answered + 1) + ' · до ' + attempt.max_questions;
    document.getElementById('placement-skill').textContent = question.skill_title;
    var progress = root.querySelector('.placement-progress');
    progress.setAttribute('aria-valuemax', attempt.max_questions); progress.setAttribute('aria-valuenow', attempt.answered);
    document.getElementById('placement-progress-fill').style.width = (attempt.answered / attempt.max_questions * 100) + '%';
    var passage = document.getElementById('placement-passage'); passage.hidden = !question.passage; passage.textContent = question.passage || '';
    document.getElementById('placement-audio-wrap').hidden = !question.audio_url;
    document.getElementById('placement-audio-retry').hidden = true;
    if (question.audio_url) audio.src = question.audio_url;
    var heading = document.getElementById('placement-question-title'); heading.textContent = question.prompt;
    var draft = read(localKey(attempt.id, question.id)); if (typeof draft !== 'string') draft = question.draft || '';
    var options = document.getElementById('placement-options-list'); options.replaceChildren();
    document.getElementById('placement-options').hidden = question.input !== 'choice';
    document.getElementById('placement-text-wrap').hidden = question.input !== 'text';
    if (question.input === 'choice') question.options.forEach(function (option, index) {
      var label = document.createElement('label'), input = document.createElement('input'), span = document.createElement('span');
      label.className = 'placement-option'; input.type = 'radio'; input.name = 'placement-option'; input.value = option;
      input.checked = draft === option; input.addEventListener('change', edit); span.textContent = option;
      label.append(input, span); options.appendChild(label);
    });
    text.value = question.input === 'text' ? draft : '';
    draftDurable = draft === (question.draft || '');
    draftStatus.textContent = pending ? 'Проверяем отправленный ответ. Повторная отправка сохранит тот же ответ.' : '';
    if (focus) { heading.focus(); heading.scrollIntoView({block: 'start'}); }
    availability();
  }
  function sendPending() {
    if (!pending) return Promise.resolve();
    var body = pending;
    return request('/' + encodeURIComponent(body.attempt) + '/answer', {question_id: body.question_id, answer: body.answer, dont_know: body.dont_know}).then(function (data) {
      pending = null; remove('pending'); remove(localKey(body.attempt, body.question_id));
      say(''); retry.hidden = true; draftDurable = true; render(data.attempt, true);
    });
  }
  function send(dontKnow) {
    if (!current || !current.question || pending) return;
    clearTimeout(draftTimer);
    var value = {attempt: current.id, question_id: current.question.id, answer: dontKnow ? '' : selected(), dont_know: dontKnow};
    if (!write('pending', value)) {
      say('Не удалось сохранить отправляемый ответ на устройстве. Освободи место или разреши хранение данных сайта и попробуй снова.');
      return;
    }
    pending = value; run(sendPending);
  }
  function start(mode) {
    return request('/start', {mode: mode}).then(function (data) { active = data.attempt; say(''); render(active, true); });
  }
  function loadStatus(restore) {
    return request('/status').then(function (data) {
      root.dataset.available = data.available ? 'true' : '';
      active = data.active; latest = data.latest;
      if (restore && pending) return sendPending();
      if (restore && latest && ((!active && guest) || new URLSearchParams(location.search).get('result') === '1')) { render(latest, false); say(''); return; }
      if (restore && active) { render(active, false); say('Продолжим с сохранённого задания.'); return; }
      stopAudio(); current = null; test.hidden = true; result.hidden = true; chooser.hidden = false; pause.hidden = true; change.hidden = true;
      resume.replaceChildren(); resume.hidden = !active;
      if (active) {
        var p = document.createElement('p'); p.textContent = 'Есть начатый ' + (active.mode === 'quick' ? 'быстрый' : 'подробный') + ' тест. Ответов сохранено: ' + active.answered + '.';
        var button = document.createElement('button'); button.type = 'button'; button.className = 'placement-secondary'; button.textContent = 'Продолжить начатый тест';
        button.addEventListener('click', function () { render(active, true); }); resume.append(p, button);
      }
      document.getElementById('placement-latest').hidden = !latest;
      say(data.available ? '' : messages.bank_unavailable);
    });
  }
  document.querySelectorAll('[data-mode]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (active && active.mode !== button.dataset.mode) { nextMode = button.dataset.mode; dialog.showModal(); }
      else run(function () { return start(button.dataset.mode); });
    });
  });
  document.getElementById('placement-change-cancel').addEventListener('click', function () { dialog.close(); if (active) render(active, true); });
  document.getElementById('placement-change-confirm').addEventListener('click', function () {
    dialog.close(); run(function () { return request('/' + active.id + '/abandon', {}).then(function () { active = null; return start(nextMode); }); });
  });
  document.getElementById('placement-latest').addEventListener('click', function () { if (latest) render(latest, true); });
  document.getElementById('placement-retake').addEventListener('click', function () { run(function () { return loadStatus(false); }); });
  change.addEventListener('click', function () { if (!pending) run(function () { return loadStatus(false); }); });
  document.getElementById('placement-apply').addEventListener('click', function () {
    if (!current || current.status !== 'completed') return;
    var button = this; button.disabled = true;
    run(function () { return request('/' + current.id + '/apply', {}).then(function (data) {
      current.applied = true; current.result.effective_on = data.attempt.effective_on; render(current, false);
    }).catch(function (error) { button.disabled = false; throw error; }); });
  });
  submit.addEventListener('click', function () { send(false); }); unknown.addEventListener('click', function () { send(true); });
  text.addEventListener('input', edit); retry.addEventListener('click', function () { run(sendPending); });
  pause.addEventListener('click', function () {
    if (!current || !current.question || pending) return;
    clearTimeout(draftTimer); var id = current.id, qid = current.question.id, value = selected();
    var local = write(localKey(id, qid), value);
    run(function () { return saveDraft(id, qid, value, local).then(function (ok) {
      if (ok === false) { say('Не удалось сохранить ответ на сервере. Попробуй ещё раз перед выходом.'); return; }
      window.location.assign(root.dataset.return);
    }); });
  });
  audio.addEventListener('error', function () {
    if (current && current.question && current.question.audio_url) {
      say('Не получилось загрузить аудио. Повтори загрузку или продолжи тест позже.');
      document.getElementById('placement-audio-retry').hidden = false;
    }
  });
  document.getElementById('placement-audio-retry').addEventListener('click', function () { audio.load(); audio.play().catch(function () {}); });
  document.addEventListener('visibilitychange', function () { if (document.hidden) audio.pause(); });
  window.addEventListener('beforeunload', function (event) {
    if (pending || (current && current.status === 'active' && !draftDurable)) { event.preventDefault(); event.returnValue = ''; }
  });
  run(function () { return loadStatus(true); });
})();
