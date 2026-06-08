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
});
