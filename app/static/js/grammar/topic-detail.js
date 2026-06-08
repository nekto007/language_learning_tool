// Get CSRF token safely
function getCSRFToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

// Complete theory
document.getElementById('complete-theory-btn')?.addEventListener('click', async function() {
  try {
    const csrfToken = getCSRFToken();
    const response = await fetch(`/grammar-lab/api/topic/${topicId}/complete-theory`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      }
    });
    const data = await response.json();

    if (data.xp_earned > 0) {
      this.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg> Изучено!';
      this.disabled = true;
      this.style.background = 'var(--grammar-surface-alt)';
      this.style.borderColor = 'var(--grammar-border)';
      this.style.color = 'var(--grammar-text-muted)';

      const notification = document.createElement('div');
      notification.className = 'xp-notification';
      notification.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg><span>+${data.xp_earned} XP</span>`;
      document.body.appendChild(notification);
      setTimeout(() => notification.remove(), 3000);
    }
  } catch (error) {
    console.error('Error completing theory:', error);
  }
});
