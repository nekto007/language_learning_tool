/**
 * Word status management functionality for the Language Learning Tool
 * Handles updating statuses of individual words and batch updates
 */

/**
 * Initialize word status change handlers
 */
function initWordStatus() {
  // Attach handlers for status dropdown items
  document.addEventListener('click', function(e) {
    const statusAction = e.target.closest('.status-action');
    if (statusAction) {
      e.preventDefault();
      e.stopPropagation();

      const wordId = parseInt(statusAction.dataset.wordId);
      const statusId = parseInt(statusAction.dataset.status);

      if (!isNaN(wordId) && !isNaN(statusId)) {
        updateWordStatus(wordId, statusId);
      }
    }
  });

  // Attach handlers for bulk status actions
  document.addEventListener('click', function(e) {
    const bulkAction = e.target.closest('.status-action-item');
    if (bulkAction) {
      e.preventDefault();
      e.stopPropagation();

      const statusId = parseInt(bulkAction.dataset.status);
      if (!isNaN(statusId)) {
        batchUpdateStatus(statusId);
      }
    }
  });

  // Initialize word detail view handlers
  document.addEventListener('click', function(e) {
    const detailsLink = e.target.closest('.view-details');
    if (detailsLink) {
      e.preventDefault();
      e.stopPropagation();

      const wordId = parseInt(detailsLink.dataset.wordId);
      if (!isNaN(wordId)) {
        showWordDetails(wordId);
      }
    }
  });

  // Make word rows clickable to view details
  document.addEventListener('click', function(e) {
    // Проверяем, что клик был по строке таблицы, но не по чекбоксу, кнопке или ссылке
    const row = e.target.closest('.word-row');
    if (row &&
        !e.target.closest('input[type="checkbox"]') &&
        !e.target.closest('button') &&
        !e.target.closest('a') &&
        !e.target.closest('.dropdown-menu')) {

      const wordId = parseInt(row.dataset.wordId);
      if (!isNaN(wordId)) {
        showWordDetails(wordId);
      }
    }
  });
}

/**
 * Update a word's status via API
 * @param {number} wordId - Word ID
 * @param {number} statusId - New status ID
 */
async function updateWordStatus(wordId, statusId) {
  // Show loading state
  const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
  if (wordRow) {
    wordRow.classList.add('opacity-50');
  }

  try {
    // Make API request
    const response = await fetch('/api/update-word-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word_id: wordId,
        status: statusId
      })
    });

    const data = await response.json();

    if (data.success) {
      // Show success message
      showToast(`Status updated successfully`, 'success');

      // Update UI to reflect the change without page reload
      updateWordStatusUI(wordId, statusId);
    } else {
      showToast(`Failed to update status: ${data.error || 'Unknown error'}`, 'danger');
      if (wordRow) {
        wordRow.classList.remove('opacity-50');
      }
    }
  } catch (error) {
    showToast(`Error updating status: ${error.message}`, 'danger');
    if (wordRow) {
      wordRow.classList.remove('opacity-50');
    }
  }
}

/**
 * Update word status in the UI without reloading
 * @param {number} wordId - Word ID
 * @param {number} statusId - New status ID
 */
function updateWordStatusUI(wordId, statusId) {
  const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
  if (!wordRow) return;

  // Remove loading state
  wordRow.classList.remove('opacity-50');

  // Update status badge
  const statusCell = wordRow.querySelector('td:nth-child(5)');
  if (statusCell) {
    const statusLabel = window.statusLabels && window.statusLabels[statusId] ?
                         window.statusLabels[statusId] : 'Unknown';
    statusCell.innerHTML = `<span class="status-badge status-${statusId}">${statusLabel}</span>`;
  }

  // Update active state in dropdown
  const dropdownItems = wordRow.querySelectorAll('.status-dropdown .dropdown-item');
  dropdownItems.forEach(item => {
    item.classList.remove('active');

    if (item.dataset.status === statusId.toString()) {
      item.classList.add('active');
    }
  });

  // Apply highlight effect to show the row was updated
  wordRow.style.transition = 'background-color 1s ease';
  wordRow.style.backgroundColor = 'rgba(var(--primary-color-rgb), 0.1)';

  setTimeout(() => {
    wordRow.style.backgroundColor = '';
  }, 1000);
}

/**
 * Handle batch status updates for multiple words
 * @param {number} statusId - Status ID to apply to all selected words
 */
async function batchUpdateStatus(statusId) {
  // Get selected word IDs from the word selection module
  const selectedWordIds = window.wordSelection?.getSelectedWordIds() || [];

  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word', 'warning');
    return;
  }

  // Get status label
  const statusLabel = window.statusLabels && window.statusLabels[statusId] ?
                      window.statusLabels[statusId] : 'Unknown';

  // Confirm action
  if (!confirm(`Are you sure you want to mark ${selectedWordIds.length} words as "${statusLabel}"?`)) {
    return;
  }

  // Update loading state
  selectedWordIds.forEach(wordId => {
    const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
    if (wordRow) {
      wordRow.classList.add('opacity-50');
    }
  });

  try {
    // Make API request
    const response = await fetch('/api/batch-update-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        word_ids: selectedWordIds,
        status: statusId
      })
    });

    const data = await response.json();

    if (data.success) {
      showToast(`Updated ${data.updated_count} of ${data.total_count} words`, 'success');

      // Update UI to reflect changes without page reload
      selectedWordIds.forEach(wordId => {
        updateWordStatusUI(wordId, statusId);
      });

      // Clear selection
      document.querySelectorAll('.word-checkbox, #selectAll').forEach(cb => {
        cb.checked = false;
      });

      // Reset selected IDs and update counters
      if (window.wordSelection) {
        window.wordSelection.selectedWordIds = [];
        window.wordSelection.updateAllSelectionCounters();
      }
    } else {
      showToast(`Failed to update status: ${data.error || 'Unknown error'}`, 'danger');

      // Remove loading state
      selectedWordIds.forEach(wordId => {
        const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
        if (wordRow) {
          wordRow.classList.remove('opacity-50');
        }
      });
    }
  } catch (error) {
    showToast(`Error updating status: ${error.message}`, 'danger');

    // Remove loading state
    selectedWordIds.forEach(wordId => {
      const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
      if (wordRow) {
        wordRow.classList.remove('opacity-50');
      }
    });
  }
}

/**
 * Show word details by navigating to detail page
 * @param {number} wordId - Word ID to show details for
 */
function showWordDetails(wordId) {
  // Просто переходим на страницу деталей слова
  window.location.href = `/word/${wordId}`;
}

/**
 * Show a toast notification (uses common.js implementation)
 * If common.js showToast isn't available, creates a basic implementation
 * @param {string} message - Message to display
 * @param {string} type - Bootstrap color type (success, danger, warning, info)
 */
function showToast(message, type = 'info') {
  // ВАЖНО: избегаем рекурсии
  // Проверяем специальный маркер источника
  if (window.showToastOrigin === 'common.js') {
    window.showToast(message, type);
    return;
  }

  // Базовая реализация для локального использования
  console.log(`[${type.toUpperCase()}] ${message}`);

  // Создаем основной контейнер toast, если его нет
  let toastContainer = document.querySelector('.toast-container');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(toastContainer);
  }

  // Создаем уведомление
  const toastId = 'toast-' + Date.now();
  const toast = document.createElement('div');
  toast.className = `toast align-items-center text-white bg-${type} border-0`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('aria-live', 'assertive');
  toast.setAttribute('aria-atomic', 'true');
  toast.setAttribute('id', toastId);

  toast.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">
        ${message}
      </div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" 
              data-bs-dismiss="toast" aria-label="Close"></button>
    </div>
  `;

  // Добавляем в контейнер
  toastContainer.appendChild(toast);

  // Инициализируем и показываем toast
  if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
    const bsToast = new bootstrap.Toast(toast, {
      delay: 3000,
      autohide: true
    });

    bsToast.show();

    // Удаляем из DOM после скрытия
    toast.addEventListener('hidden.bs.toast', function() {
      toast.remove();
    });
  } else {
    // Резервная реализация если bootstrap недоступен
    toast.style.opacity = '1';
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.5s';
      setTimeout(() => toast.remove(), 500);
    }, 3000);
  }
}

// Устанавливаем маркер только если не был установлен другой
if (typeof window.showToastOrigin === 'undefined') {
  window.showToastOrigin = 'word-status.js';
}

// Initialize word status functionality when DOM is ready
document.addEventListener('DOMContentLoaded', initWordStatus);

// Export functions for use in other modules
window.wordStatus = {
  updateWordStatus,
  updateWordStatusUI,
  batchUpdateStatus,
  showWordDetails
};