// Get CSRF token safely
function getCSRFToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

function markTheoryButtonDone(btn) {
  btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Изучено!';
  btn.disabled = true;
  btn.style.background = 'var(--grammar-surface-alt)';
  btn.style.borderColor = 'var(--grammar-border)';
  btn.style.color = 'var(--grammar-text-muted)';
}

function showTheoryError(btn, message) {
  let el = document.getElementById('complete-theory-error');
  if (!el) {
    el = document.createElement('div');
    el.id = 'complete-theory-error';
    el.className = 'alert alert--form-error';
    el.setAttribute('role', 'alert');
    btn.insertAdjacentElement('afterend', el);
  }
  el.textContent = message;
}

// Complete theory
document.getElementById('complete-theory-btn')?.addEventListener('click', async function() {
  // UI-012: the button stayed live during the request and every failure mode was
  // invisible — a 500 with an HTML body rejected inside response.json(), and a
  // JSON error body left `data.xp_earned` undefined, which made the guard below
  // false and skipped the whole success block. Either way the page did not move
  // and the learner clicked again.
  const btn = this;
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.classList.add('btn--loading');

  try {
    const csrfToken = getCSRFToken();
    const response = await fetch(`/grammar-lab/api/topic/${topicId}/complete-theory`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      }
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (data && data.error) throw new Error(data.error);

    // The endpoint is idempotent: a repeat click returns xp_earned = 0 and that
    // is still a success, so the button must settle either way.
    btn.classList.remove('btn--loading');
    markTheoryButtonDone(btn);

    if (data && data.xp_earned > 0) {
      const notification = document.createElement('div');
      notification.className = 'xp-notification';
      notification.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>+${data.xp_earned} XP</span>`;
      document.body.appendChild(notification);
      setTimeout(() => notification.remove(), 3000);
    }
  } catch (error) {
    console.error('Error completing theory:', error);
    btn.classList.remove('btn--loading');
    btn.innerHTML = originalHtml;
    btn.disabled = false;
    showTheoryError(btn, 'Не удалось отметить теорию изученной. Попробуйте ещё раз.');
  }
});
