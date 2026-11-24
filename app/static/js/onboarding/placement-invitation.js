(() => {
  const card = document.querySelector('[data-placement-invitation]');
  if (!card) return;
  const button = card.querySelector('[data-placement-dismiss]');
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const response = await fetch('/onboarding/placement/v2/dismiss', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-LLT-Account-ID': card.dataset.account,
          'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
        body: JSON.stringify({key: card.dataset.key})
      });
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error();
      card.remove();
    } catch (_) {
      const note = card.querySelector('[data-placement-notice]');
      note.hidden = false; note.textContent = 'Не удалось сохранить выбор. Попробуй ещё раз.';
      button.disabled = false;
    }
  });
})();
