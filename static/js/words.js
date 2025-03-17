/**
 * Words List Page Specific JavaScript
 */

// Variables to store page state
let selectedWordIds = [];

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
  // Initialize components
  initWordSelection();
  initWordStatusChanges();
  initFilterToggle();
  initWordRowClicks();
  initAnkiExport();
  initSearchFocus();
  initPronunciationButtons();

  // Initialize bulk actions
  document.querySelectorAll('.status-action-item').forEach(item => {
    item.addEventListener('click', function(e) {
      e.preventDefault();
      const statusId = this.getAttribute('data-status');
      batchUpdateStatus(statusId);
    });
  });

  // Create Anki button
  document.getElementById('createAnkiBtn')?.addEventListener('click', function(e) {
    e.preventDefault();
    openAnkiExportModal();
  });
});

/**
 * Initialize pronunciation player buttons in the table
 */
function initPronunciationButtons() {
  document.querySelectorAll('.action-buttons .btn-icon').forEach(button => {
    if (button.disabled) return;

    button.addEventListener('click', function(e) {
      e.stopPropagation();
      const wordId = this.closest('.word-row').getAttribute('data-word-id');
      const wordText = this.closest('.word-row').querySelector('td:nth-child(2)').textContent.trim();

      // Create audio element if it doesn't exist
      let audio = document.getElementById(`audio-${wordId}`);
      if (!audio) {
        audio = document.createElement('audio');
        audio.id = `audio-${wordId}`;
        audio.src = `/media/pronunciation_en_${wordText.toLowerCase().replace(/\s+/g, '_')}.mp3`;
        document.body.appendChild(audio);
      }

      // Play the audio
      audio.play().catch(error => {
        console.error('Error playing audio:', error);
        showToast('Error playing pronunciation', 'danger');
      });
    });
  });
}

/**
 * Handle word selection functionality (checkboxes)
 */
function initWordSelection() {
  const selectAll = document.getElementById('selectAll');
  const wordCheckboxes = document.querySelectorAll('.word-checkbox');
  const selectedCountElement = document.getElementById('selectedCount');

  if (!selectAll || !wordCheckboxes.length) return;

  // Select all checkbox change handler
  selectAll.addEventListener('change', function() {
    const isChecked = this.checked;

    wordCheckboxes.forEach(checkbox => {
      checkbox.checked = isChecked;

      // Update selected word IDs list
      const wordId = parseInt(checkbox.getAttribute('data-word-id'));
      if (isChecked) {
        if (!selectedWordIds.includes(wordId)) {
          selectedWordIds.push(wordId);
        }
      } else {
        selectedWordIds = selectedWordIds.filter(id => id !== wordId);
      }
    });

    updateSelectedCount();
    updateBulkActionState();
  });

  // Individual checkbox change handlers
  wordCheckboxes.forEach(checkbox => {
    checkbox.addEventListener('change', function() {
      const wordId = parseInt(this.getAttribute('data-word-id'));

      if (this.checked) {
        if (!selectedWordIds.includes(wordId)) {
          selectedWordIds.push(wordId);
        }
      } else {
        selectedWordIds = selectedWordIds.filter(id => id !== wordId);
      }

      updateSelectedCount();
      updateSelectAllState();
      updateBulkActionState();
    });
  });

  // Update selected count display
  function updateSelectedCount() {
    if (selectedCountElement) {
      selectedCountElement.textContent = `${selectedWordIds.length} selected`;
    }
  }

  // Update select all checkbox state
  function updateSelectAllState() {
    if (!selectAll) return;

    const allChecked = Array.from(wordCheckboxes).every(cb => cb.checked);
    const anyChecked = Array.from(wordCheckboxes).some(cb => cb.checked);

    selectAll.checked = allChecked;
    selectAll.indeterminate = anyChecked && !allChecked;
  }

  // Update bulk action button state
  function updateBulkActionState() {
    const bulkActionsBtn = document.getElementById('bulkActionsBtn');
    if (bulkActionsBtn) {
      bulkActionsBtn.disabled = selectedWordIds.length === 0;
    }
  }
}

/**
 * Handle word status changes
 */
function initWordStatusChanges() {
  // Status dropdown items
  document.querySelectorAll('.dropdown-item[onclick*="updateWordStatus"]').forEach(item => {
    item.addEventListener('click', function(e) {
      e.stopPropagation();

      // Extract word ID and status from onclick attribute
      const onclickAttr = this.getAttribute('onclick');
      const match = onclickAttr.match(/updateWordStatus\((\d+),\s*(\d+)\)/);

      if (match && match.length === 3) {
        const wordId = parseInt(match[1]);
        const statusId = parseInt(match[2]);

        updateWordStatus(wordId, statusId);
        return false;
      }
    });
  });
}

/**
 * Update a word's status via API
 * @param {number} wordId - Word ID
 * @param {number} statusId - New status ID
 */
function updateWordStatus(wordId, statusId) {
  // Show loading state
  const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
  if (wordRow) {
    wordRow.classList.add('opacity-50');
  }

  // Call API to update status
  callApi('/api/update-word-status', {
    method: 'POST',
    body: JSON.stringify({
      word_id: wordId,
      status: statusId
    })
  },
  // Success callback
  function(data) {
    if (data.success) {
      // Show success message
      showToast(`Status updated successfully`, 'success');

      // Update UI to reflect the change without page reload
      updateWordStatusUI(wordId, statusId);
    } else {
      showToast(`Failed to update status: ${data.error}`, 'danger');
      if (wordRow) {
        wordRow.classList.remove('opacity-50');
      }
    }
  },
  // Error callback
  function(error) {
    showToast(`Error updating status: ${error.message}`, 'danger');
    if (wordRow) {
      wordRow.classList.remove('opacity-50');
    }
  });
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
    const statusLabel = statusLabels[statusId] || 'Unknown';
    statusCell.innerHTML = `<span class="status-badge status-${statusId}">${statusLabel}</span>`;
  }

  // Update active state in dropdown
  const dropdownItems = wordRow.querySelectorAll('.status-dropdown .dropdown-item');
  dropdownItems.forEach(item => {
    item.classList.remove('active');

    const onclickAttr = item.getAttribute('onclick');
    if (onclickAttr && onclickAttr.includes(`updateWordStatus(${wordId}, ${statusId})`)) {
      item.classList.add('active');
    }
  });

  // Apply highlight effect
  wordRow.style.transition = 'background-color 1s ease';
  wordRow.style.backgroundColor = 'rgba(var(--primary-color-rgb), 0.1)';

  setTimeout(() => {
    wordRow.style.backgroundColor = '';
  }, 1000);
}

/**
 * Handle batch status updates
 * @param {number} statusId - Status ID to apply to all selected words
 */
function batchUpdateStatus(statusId) {
  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word', 'warning');
    return;
  }

  // Get status label
  const statusLabel = statusLabels[statusId] || 'Unknown';

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

  // Call API to update all selected words
  callApi('/api/batch-update-status', {
    method: 'POST',
    body: JSON.stringify({
      word_ids: selectedWordIds,
      status: statusId
    })
  },
  // Success callback
  function(data) {
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
      selectedWordIds = [];
      updateSelectedCount();
    } else {
      showToast(`Failed to update status: ${data.error}`, 'danger');

      // Remove loading state
      selectedWordIds.forEach(wordId => {
        const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
        if (wordRow) {
          wordRow.classList.remove('opacity-50');
        }
      });
    }
  },
  // Error callback
  function(error) {
    showToast(`Error updating status: ${error.message}`, 'danger');

    // Remove loading state
    selectedWordIds.forEach(wordId => {
      const wordRow = document.querySelector(`.word-row[data-word-id="${wordId}"]`);
      if (wordRow) {
        wordRow.classList.remove('opacity-50');
      }
    });
  });
}

/**
 * Initialize filter toggle
 */
function initFilterToggle() {
  const showAllToggle = document.getElementById('showAllToggle');
  if (!showAllToggle) return;

  showAllToggle.addEventListener('change', function() {
    const url = new URL(window.location.href);
    url.searchParams.set('show_all', this.checked ? 1 : 0);
    url.searchParams.set('page', 1); // Reset to first page
    window.location.href = url.toString();
  });
}

/**
 * Initialize row clicks to view word details
 */
function initWordRowClicks() {
  const wordRows = document.querySelectorAll('.word-row');
  wordRows.forEach(row => {
    row.addEventListener('click', function(e) {
      // Don't trigger if clicking on a checkbox, button, or link
      if (e.target.closest('input[type="checkbox"]') ||
          e.target.closest('button') ||
          e.target.closest('a') ||
          e.target.closest('.dropdown-menu')) {
        return;
      }

      // Get word ID and navigate to word detail page
      const wordId = this.getAttribute('data-word-id');
      window.location.href = `/word/${wordId}`;
    });
  });
}

/**
 * Initialize Anki export functionality
 */
function initAnkiExport() {
  // Update preview on toggle changes
  document.querySelectorAll('#includePronunciation, #includeExamples').forEach(checkbox => {
    checkbox?.addEventListener('change', updateAnkiPreview);
  });

  // Export button handler
  document.getElementById('exportAnkiBtn')?.addEventListener('click', exportAnkiDeck);
}

/**
 * Open the Anki export modal
 */
function openAnkiExportModal() {
  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word to create cards', 'warning');
    return;
  }

  // Update word count
  document.getElementById('selectedWordsCount').textContent = `Selected words: ${selectedWordIds.length}`;

  // Show modal
  const ankiModal = new bootstrap.Modal(document.getElementById('ankiExportModal'));
  ankiModal.show();

  // Update preview
  updateAnkiPreview();
}

/**
 * Update Anki card preview based on settings
 */
function updateAnkiPreview() {
  const includePronunciation = document.getElementById('includePronunciation').checked;
  const includeExamples = document.getElementById('includeExamples').checked;

  // Update preview elements visibility
  const pronunciationElements = document.querySelectorAll('#previewPronunciation, #backPronunciation');
  pronunciationElements.forEach(el => {
    el.style.display = includePronunciation ? 'block' : 'none';
  });

  const exampleElement = document.getElementById('previewExample');
  if (exampleElement) {
    exampleElement.style.display = includeExamples ? 'block' : 'none';
  }
}

/**
 * Export selected words as an Anki deck
 */
function exportAnkiDeck() {
  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word to create cards', 'warning');
    return;
  }

  // Get export settings
  const exportSettings = {
    deckName: document.getElementById('deckName').value || 'Vocabulary',
    cardFormat: document.querySelector('input[name="cardFormat"]:checked').value,
    includePronunciation: document.getElementById('includePronunciation').checked,
    includeExamples: document.getElementById('includeExamples').checked,
    updateStatus: document.getElementById('updateStatus').checked,
    wordIds: selectedWordIds
  };

  // Update button state
  const exportBtn = document.getElementById('exportAnkiBtn');
  const originalText = exportBtn.innerHTML;
  exportBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Creating deck...';
  exportBtn.disabled = true;

  // Call API to create deck
  fetch('/api/export-anki', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(exportSettings)
  })
  .then(response => {
    if (!response.ok) {
      throw new Error('Server error during export');
    }
    return response.blob();
  })
  .then(blob => {
    // Create download link
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `${exportSettings.deckName}.apkg`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);

    // Restore button
    exportBtn.innerHTML = originalText;
    exportBtn.disabled = false;

    // Close modal
    const ankiModal = bootstrap.Modal.getInstance(document.getElementById('ankiExportModal'));
    if (ankiModal) {
      ankiModal.hide();
    }

    // Show success message
    showToast('Anki deck created successfully', 'success');

    // If status update is needed, update UI
    if (exportSettings.updateStatus) {
      selectedWordIds.forEach(wordId => {
        updateWordStatusUI(wordId, 3); // 3 is "Active" status
      });

      // Clear selection
      document.querySelectorAll('.word-checkbox, #selectAll').forEach(cb => {
        cb.checked = false;
      });
      selectedWordIds = [];
      updateSelectedCount();
    }
  })
  .catch(error => {
    console.error('Error:', error);
    showToast(`An error occurred: ${error.message}`, 'danger');

    // Restore button
    exportBtn.innerHTML = originalText;
    exportBtn.disabled = false;
  });
}

/**
 * Initialize search input focus
 */
function initSearchFocus() {
  const searchInput = document.getElementById('searchInput');
  if (searchInput && searchInput.value) {
    searchInput.focus();
    // Place cursor at the end of text
    const length = searchInput.value.length;
    searchInput.setSelectionRange(length, length);
  }

  // Search on Enter key press
  searchInput?.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      this.closest('form').submit();
    }
  });
}

/**
 * Update selected count display
 */
function updateSelectedCount() {
  const selectedCountElement = document.getElementById('selectedCount');
  if (selectedCountElement) {
    selectedCountElement.textContent = `${selectedWordIds.length} selected`;
  }
}