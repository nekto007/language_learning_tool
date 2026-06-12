document.addEventListener('DOMContentLoaded', function() {
  var currentStep = 1;
  var selectedLevel = '';
  var selectedFocuses = [];

  var steps = {
    1: document.getElementById('step1'),
    2: document.getElementById('step2'),
    3: document.getElementById('step3')
  };
  var progressBar = document.getElementById('progressBar');
  var backBtn = document.getElementById('backBtn');
  var focusNextBtn = document.getElementById('focusNextBtn');

  function showStep(n) {
    for (var k in steps) {
      steps[k].style.display = k == n ? '' : 'none';
    }
    var pct = Math.round(n * 33.33);
    progressBar.style.width = pct + '%';
    var pc = document.getElementById('progressContainer');
    if (pc) pc.setAttribute('aria-valuenow', String(pct));
    backBtn.style.display = n > 1 ? '' : 'none';
    currentStep = n;
  }

  // Step 1: Level selection
  document.querySelectorAll('.onboarding-level-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.onboarding-level-btn').forEach(function(b) { b.classList.remove('selected'); });
      btn.classList.add('selected');
      selectedLevel = btn.dataset.level;
      document.getElementById('selectedLevel').value = selectedLevel;
      // Auto-advance after short delay
      setTimeout(function() { showStep(2); }, 250);
    });
  });

  // Step 2: Focus selection
  document.querySelectorAll('.onboarding-focus-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var focus = btn.dataset.focus;
      if (focus === 'all') {
        // "All" deselects others
        document.querySelectorAll('.onboarding-focus-btn').forEach(function(b) { b.classList.remove('selected'); });
        btn.classList.add('selected');
        selectedFocuses = ['all'];
      } else {
        // Deselect "all" if selected
        var allBtn = document.querySelector('.onboarding-focus-btn[data-focus="all"]');
        if (allBtn) allBtn.classList.remove('selected');
        selectedFocuses = selectedFocuses.filter(function(f) { return f !== 'all'; });

        if (btn.classList.contains('selected')) {
          btn.classList.remove('selected');
          selectedFocuses = selectedFocuses.filter(function(f) { return f !== focus; });
        } else {
          btn.classList.add('selected');
          selectedFocuses.push(focus);
        }
      }
      document.getElementById('selectedFocus').value = selectedFocuses.join(',');
      focusNextBtn.disabled = selectedFocuses.length === 0;
    });
  });

  focusNextBtn.addEventListener('click', function() {
    if (selectedFocuses.length === 0) return;

    // Build summary
    var levelNames = {A1:'Beginner',A2:'Elementary',B1:'Intermediate',B2:'Upper-Intermediate',C1:'Advanced'};
    var focusNames = {grammar:'Грамматика',vocabulary:'Слова',reading:'Чтение',all:'Всё сразу'};
    var summary = '<strong>Уровень:</strong> ' + selectedLevel + ' — ' + (levelNames[selectedLevel]||'') + '<br>';
    summary += '<strong>Фокус:</strong> ' + selectedFocuses.map(function(f){return focusNames[f]||f;}).join(', ');
    document.getElementById('readySummary').innerHTML = summary;

    showStep(3);
  });

  // Back button
  backBtn.querySelector('button').addEventListener('click', function() {
    if (currentStep > 1) showStep(currentStep - 1);
  });

  // Placement test (рендерится только при наличии пула вопросов)
  var placementStartBtn = document.getElementById('placementStartBtn');
  if (placementStartBtn) {
    var placementPanel = document.getElementById('placementPanel');
    var placementProgress = document.getElementById('placementProgress');
    var placementQuestion = document.getElementById('placementQuestion');
    var placementOptions = document.getElementById('placementOptions');
    var placementResult = document.getElementById('placementResult');
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.content : '';
    var currentQuestion = null;

    function postJSON(url, body) {
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify(body || {})
      }).then(function(r) { return r.json(); });
    }

    function placementFail() {
      placementResult.hidden = false;
      placementResult.textContent = 'Тест прервался — выберите уровень вручную выше.';
      placementQuestion.textContent = '';
      placementOptions.textContent = '';
      placementProgress.textContent = '';
    }

    function renderQuestion(payload) {
      currentQuestion = payload.question;
      placementProgress.textContent = 'Вопрос ' + payload.number + ' из ' + payload.max;
      placementQuestion.textContent = payload.question.question;
      placementOptions.textContent = '';
      payload.question.options.forEach(function(opt) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'onboarding-placement__option';
        b.textContent = opt;
        b.addEventListener('click', function() { sendAnswer(opt); });
        placementOptions.appendChild(b);
      });
    }

    function showRecommendation(d) {
      placementQuestion.textContent = '';
      placementOptions.textContent = '';
      placementProgress.textContent = '';
      placementResult.hidden = false;
      placementResult.textContent = '';
      var text = document.createElement('div');
      text.className = 'onboarding-placement__verdict';
      text.textContent = 'Ваш уровень: ' + d.recommended_level +
        ' (' + d.correct_count + ' из ' + d.total + ' верно)';
      placementResult.appendChild(text);
      var applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'onboarding-placement__apply';
      applyBtn.textContent = 'Продолжить с уровнем ' + d.recommended_level;
      applyBtn.addEventListener('click', function() {
        var levelBtn = document.querySelector('.onboarding-level-btn[data-level="' + d.recommended_level + '"]');
        if (levelBtn) levelBtn.click();
      });
      placementResult.appendChild(applyBtn);
      var note = document.createElement('div');
      note.className = 'onboarding-placement__note';
      note.textContent = 'Можно выбрать другой уровень вручную выше.';
      placementResult.appendChild(note);
    }

    function sendAnswer(opt) {
      Array.prototype.forEach.call(placementOptions.children, function(b) { b.disabled = true; });
      postJSON('/onboarding/placement/answer', {
        exercise_id: currentQuestion.id,
        answer: opt
      }).then(function(d) {
        if (!d.success) { placementFail(); return; }
        if (d.done) { showRecommendation(d); } else { renderQuestion(d.next); }
      }).catch(placementFail);
    }

    placementStartBtn.addEventListener('click', function() {
      placementStartBtn.disabled = true;
      postJSON('/onboarding/placement/start').then(function(d) {
        if (!d.success) { placementStartBtn.textContent = 'Тест сейчас недоступен'; return; }
        placementStartBtn.hidden = true;
        placementPanel.hidden = false;
        placementResult.hidden = true;
        renderQuestion(d);
      }).catch(function() {
        placementStartBtn.disabled = false;
      });
    });
  }
});
