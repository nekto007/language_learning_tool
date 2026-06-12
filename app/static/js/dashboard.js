(function () {
        var popup = document.getElementById('dash-badge-popup');
        if (!popup) return;
        var cards = popup.querySelectorAll('.dash-badge-popup__card');
        cards.forEach(function (card, idx) {
          var baseDelay = 5000 + idx * 150;
          setTimeout(function () {
            card.classList.add('dash-badge-popup__card--dismissed');
          }, baseDelay);
        });
      })();

(function () {
            var flash = document.querySelector('[data-streak-flash="true"]');
            if (!flash) return;
            setTimeout(function () { flash.remove(); }, 2500);
        })();

(function () {
        var card = document.getElementById('weekly-report-card');
        if (!card) return;
        var btn = card.querySelector('[data-action="dismiss-weekly-report"]');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var key = card.getAttribute('data-dismiss-key');
            fetch('/api/weekly-report/dismiss', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': (document.querySelector('meta[name=csrf-token]') || {}).content || ''},
                body: JSON.stringify({dismiss_key: key}),
                credentials: 'same-origin'
            });
            card.style.display = 'none';
        });
    })();

async function repairStreak() {
    const btn = document.getElementById('repair-streak-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '...';
    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.content : '';
        const resp = await fetch('/api/streak/repair-web', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({tz: Intl.DateTimeFormat().resolvedOptions().timeZone})
        });
        const data = await resp.json();
        if (data.success) {
            location.reload();
        } else {
            const msg = data.error === 'insufficient_coins'
                ? 'Недостаточно coins (нужно ' + data.cost + ', баланс ' + data.balance + ')'
                : 'Не удалось восстановить серию';
            alert(msg);
            btn.disabled = false;
            btn.textContent = 'Восстановить';
        }
    } catch(e) {
        alert('Ошибка сети');
        btn.disabled = false;
        btn.textContent = 'Восстановить';
    }
}

// Milestone badge: show animation only once per streak value
(function() {
    var badge = document.getElementById('milestone-badge');
    if (badge) {
        var streak = window.DASHBOARD_STREAK || 0;
        var key = 'milestone_seen_' + streak;
        if (localStorage.getItem(key)) {
            badge.style.animation = 'none';
        } else {
            localStorage.setItem(key, '1');
        }
    }
})();

// Task 7: Phase transition animations triggered when returning from a daily-plan step.
// Strategy: persist last-seen done-phase-ids per URL in sessionStorage. On load, diff
// against current done phases — any new done phase gets a one-shot "just-completed"
// class, and the newly-current phase gets a "newly-active" pulse.
(function() {
    var missionAttr = 'data-mission' + '-plan';
    var timeline = document.querySelector('[' + missionAttr + '="true"]');
    if (!timeline) return;

    var steps = timeline.querySelectorAll('.dash-step--phase[data-phase-id]');
    if (!steps.length) return;

    var storeKey = 'mission_phase_states_v1';
    var currentDone = [];
    steps.forEach(function(step) {
        if (step.getAttribute('data-phase-state') === 'done') {
            currentDone.push(step.getAttribute('data-phase-id'));
        }
    });

    var params = new URLSearchParams(window.location.search);
    var cameFromPlan = params.get('from') === 'daily_plan';

    var previousDone = [];
    try {
        var raw = sessionStorage.getItem(storeKey);
        if (raw) {
            var parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) previousDone = parsed;
        }
    } catch (e) {
        previousDone = [];
    }

    if (cameFromPlan) {
        var newlyDone = currentDone.filter(function(id) { return previousDone.indexOf(id) === -1; });
        if (newlyDone.length) {
            steps.forEach(function(step) {
                var id = step.getAttribute('data-phase-id');
                if (newlyDone.indexOf(id) !== -1) {
                    step.classList.add('dash-step--just-completed');
                }
                if (step.getAttribute('data-phase-state') === 'current') {
                    step.classList.add('dash-step--newly-active');
                }
            });
        }
    }

    try {
        sessionStorage.setItem(storeKey, JSON.stringify(currentDone));
    } catch (e) { /* storage full or disabled — non-fatal */ }
})();

// Task 35: Route overtake and checkpoint animations.
// Persists route positions in sessionStorage; on ?from=daily_plan detects:
//   - newly reached checkpoint → pulse the current roadmap node
//   - newly completed checkpoint → pop-in animation on done roadmap node
//   - overtake (user moved past a rival) → bounce + flash on user token
//   - calm finish on first all-done visit
(function() {
    var params = new URLSearchParams(window.location.search);
    var cameFromPlan = params.get('from') === 'daily_plan';
    var routeContainer = document.querySelector('[data-route-container="true"]');
    if (!routeContainer || !cameFromPlan) {
        // Still persist current state even if not animating, so next visit has a baseline
        if (routeContainer) {
            var tokens35 = routeContainer.querySelectorAll('[data-animate-token="true"]');
            var pos35 = {};
            tokens35.forEach(function(tok) {
                pos35[tok.getAttribute('data-token-role')] = parseFloat(tok.getAttribute('data-route-position') || '0');
            });
            try {
                sessionStorage.setItem('mission_route_state_v1', JSON.stringify({
                    positions: pos35,
                    checkpoint: parseInt(routeContainer.getAttribute('data-current-checkpoint') || '0', 10),
                    finishState: routeContainer.getAttribute('data-finish-state') || ''
                }));
            } catch (e) { /* non-fatal */ }
        }
        return;
    }

    var storeKey35 = 'mission_route_state_v1';
    var finishState = routeContainer.getAttribute('data-finish-state') || '';
    var currentCheckpoint = parseInt(routeContainer.getAttribute('data-current-checkpoint') || '0', 10);

    var tokens = routeContainer.querySelectorAll('[data-animate-token="true"]');
    var currentPositions = {};
    tokens.forEach(function(tok) {
        currentPositions[tok.getAttribute('data-token-role')] = parseFloat(tok.getAttribute('data-route-position') || '0');
    });

    var prev = {};
    try {
        var raw = sessionStorage.getItem(storeKey35);
        if (raw) prev = JSON.parse(raw);
    } catch (e) { prev = {}; }

    var prevPositions  = prev.positions  || {};
    var prevCheckpoint = (prev.checkpoint != null) ? prev.checkpoint : currentCheckpoint;
    var prevFinish     = prev.finishState || '';

    // Detect user token movement
    var myCurrentPos = currentPositions['me'];
    var myPrevPos    = prevPositions['me'];
    var userMoved    = (myCurrentPos != null && myPrevPos != null && myCurrentPos > myPrevPos);

    if (userMoved) {
        tokens.forEach(function(tok) {
            if (tok.getAttribute('data-token-role') === 'me') {
                tok.classList.add('dash-route-token--just-moved');
            }
        });

        // Overtake detection: rival was ahead of user before, now is at or behind user
        tokens.forEach(function(tok) {
            var role = tok.getAttribute('data-token-role');
            if (role === 'me' || role === 'behind') return;
            var rivalCurrent = parseFloat(tok.getAttribute('data-route-position') || '0');
            var rivalPrev    = prevPositions[role];
            if (rivalPrev != null && rivalPrev > myPrevPos && rivalCurrent <= myCurrentPos) {
                tokens.forEach(function(t) {
                    if (t.getAttribute('data-token-role') === 'me') {
                        t.classList.add('dash-route-token--overtaking');
                        var toast = document.createElement('span');
                        toast.className = 'dash-route-overtake-toast';
                        toast.setAttribute('data-overtake-toast', 'true');
                        toast.textContent = 'Обгон!';
                        t.appendChild(toast);
                    }
                });
            }
        });
    }

    // Checkpoint transition animations
    if (currentCheckpoint !== prevCheckpoint) {
        var nodes = routeContainer.querySelectorAll('[data-roadmap-node="true"]');
        nodes.forEach(function(node) {
            var idx   = parseInt(node.getAttribute('data-node-index') || '0', 10);
            var state = node.getAttribute('data-node-state');
            if (state === 'current' && idx === currentCheckpoint) {
                node.classList.add('dash-roadmap__node--just-reached');
            }
            if (state === 'done' && idx === prevCheckpoint) {
                node.classList.add('dash-roadmap__node--just-completed');
            }
        });
    }

    // Calm finish animation on first all-done visit
    if (finishState === 'done' && prevFinish !== 'done') {
        routeContainer.classList.add('dash-route--finish-calm');
    }

    // Persist current state
    try {
        sessionStorage.setItem(storeKey35, JSON.stringify({
            positions: currentPositions,
            checkpoint: currentCheckpoint,
            finishState: finishState
        }));
    } catch (e) { /* non-fatal */ }
})();


// CSP-safe delegated handlers for dashboard actions
document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  var action = t.getAttribute('data-action');
  if (action === 'dismiss-badge') {
    var card = t.closest('.dash-badge-popup__card');
    if (card) card.classList.add('dash-badge-popup__card--dismissed');
  } else if (action === 'share-streak-telegram') {
    if (typeof shareVia === 'function') {
      var txt = t.getAttribute('data-share-text') || '';
      var ref = t.getAttribute('data-share-ref') || '';
      shareVia('telegram', txt, window.location.origin + '/register?ref=' + encodeURIComponent(ref));
    }
  } else if (action === 'repair-streak') {
    if (typeof repairStreak === 'function') repairStreak();
  } else if (action === 'share-day-results') {
    var msg = t.getAttribute('data-share-text') || '';
    var shareUrl = t.getAttribute('data-share-url') || '';
    var fullText = shareUrl ? msg + ' ' + shareUrl : msg;
    var fallbackPrompt = function() { try { window.prompt('Скопируйте текст:', fullText); } catch (e) {} };
    var copyToClipboard = function() {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(fullText).then(function() {
          t.textContent = 'Скопировано!';
          setTimeout(function() { t.textContent = 'Поделиться'; }, 2000);
        }).catch(fallbackPrompt);
      } else {
        fallbackPrompt();
      }
    };
    if (navigator.share) {
      var payload = shareUrl ? { text: msg, url: shareUrl } : { text: msg };
      navigator.share(payload).catch(function(err) {
        if (err && err.name === 'AbortError') return;
        copyToClipboard();
      });
    } else {
      copyToClipboard();
    }
  }
});
