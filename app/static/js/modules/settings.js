function toggleModule(moduleId, enabled) {
    fetch(`/modules/api/modules/${moduleId}/toggle`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]')||{}).content || ''
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const status = data.enabled ? 'включен' : 'отключен';
            showMsToast('success', `Модуль успешно ${status}`);

            // Reload after a short delay to update navigation
            setTimeout(() => {
                location.reload();
            }, 1500);
        } else {
            showMsToast('error', data.error || 'Ошибка при изменении модуля');
            // Revert checkbox state
            document.getElementById(`module_${moduleId}`).checked = !enabled;
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showMsToast('error', 'Произошла ошибка при обновлении модуля');
        // Revert checkbox state
        document.getElementById(`module_${moduleId}`).checked = !enabled;
    });
}

function showMsToast(type, message) {
    const container = document.getElementById('msToastContainer');
    const toast = document.createElement('div');
    toast.className = `ms-toast ms-toast--${type}`;

    const iconSvg = type === 'success'
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';

    toast.innerHTML = `<span class="ms-toast__icon">${iconSvg}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
