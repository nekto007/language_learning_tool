/**
 * Word selection functionality for the Language Learning Tool
 * Handles checkbox selection and counting of selected words
 */

// Global state for selected words
let selectedWordIds = [];

/**
 * Initialize word selection functionality
 */
function initWordSelection() {
  const selectAllCheckbox = document.getElementById('selectAll');
  const wordCheckboxes = document.querySelectorAll('.word-checkbox');

  if (!selectAllCheckbox || !wordCheckboxes.length) return;

  // Select/deselect all words
  selectAllCheckbox.addEventListener('change', function() {
    const isChecked = this.checked;

    wordCheckboxes.forEach(checkbox => {
      checkbox.checked = isChecked;

      const wordId = parseInt(checkbox.dataset.wordId);
      if (isChecked && !selectedWordIds.includes(wordId)) {
        selectedWordIds.push(wordId);
      }
    });

    if (!isChecked) {
      selectedWordIds = [];
    }

    updateAllSelectionCounters();
    updateBulkActionState();
  });

  // Handle individual checkbox changes
  wordCheckboxes.forEach(checkbox => {
    checkbox.addEventListener('change', function() {
      const wordId = parseInt(this.dataset.wordId);

      if (this.checked && !selectedWordIds.includes(wordId)) {
        selectedWordIds.push(wordId);
      } else if (!this.checked) {
        selectedWordIds = selectedWordIds.filter(id => id !== wordId);
      }

      updateAllSelectionCounters();
      updateSelectAllCheckbox();
      updateBulkActionState();
    });
  });

  // Initial update
  updateAllSelectionCounters();
  updateSelectAllCheckbox();
  updateBulkActionState();
}

/**
 * Update all counters that display the number of selected words
 */
function updateAllSelectionCounters() {
  const count = selectedWordIds.length;

  // Update main counter
  const counterElement = document.getElementById('selectedCount');
  if (counterElement) {
    counterElement.textContent = `${count} selected`;
  }

  // Update Anki counter
  const ankiCountElement = document.getElementById('ankiSelectedWordsCount');
  if (ankiCountElement) {
    ankiCountElement.textContent = `Selected words: ${count}`;
  }

  // Update SRS deck counters
  const counters = ['selectedWordsCount', 'importWordsCount'];
  counters.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.textContent = count;
    }
  });
}

/**
 * Update the "select all" checkbox state based on individual selections
 */
function updateSelectAllCheckbox() {
  const selectAllCheckbox = document.getElementById('selectAll');
  const wordCheckboxes = document.querySelectorAll('.word-checkbox');

  if (!selectAllCheckbox || !wordCheckboxes.length) return;

  const allChecked = Array.from(wordCheckboxes).every(cb => cb.checked);
  const someChecked = Array.from(wordCheckboxes).some(cb => cb.checked);

  selectAllCheckbox.checked = allChecked;
  selectAllCheckbox.indeterminate = someChecked && !allChecked;
}

/**
 * Enable/disable bulk action buttons based on selection
 */
function updateBulkActionState() {
  const hasSelection = selectedWordIds.length > 0;

  // Bulk actions dropdown
  const bulkActionsBtn = document.getElementById('bulkActionsBtn');
  if (bulkActionsBtn) {
    bulkActionsBtn.disabled = !hasSelection;
  }

  // Create Anki button
  const createAnkiBtn = document.getElementById('createAnkiBtn');
  if (createAnkiBtn) {
    createAnkiBtn.classList.toggle('disabled', !hasSelection);
  }

  // SRS deck buttons
  const createDeckBtn = document.getElementById('createDeckWithWordsBtn');
  const importBtn = document.getElementById('importWordsToDeckBtn');

  if (createDeckBtn) {
    createDeckBtn.disabled = !hasSelection;
  }

  if (importBtn) {
    importBtn.disabled = !hasSelection;
  }
}

/**
 * Get the list of currently selected word IDs
 * @returns {Array} Array of selected word IDs as integers
 */
function getSelectedWordIds() {
  return selectedWordIds;
}

// Initialize the selection functionality when the DOM is loaded
document.addEventListener('DOMContentLoaded', initWordSelection);

// Export for use in other modules
window.wordSelection = {
  getSelectedWordIds,
  updateAllSelectionCounters,
  selectedWordIds
};