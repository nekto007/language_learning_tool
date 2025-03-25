/**
 * Anki export functionality for the Language Learning Tool
 * Handles creation and export of Anki flashcard decks
 */

/**
 * Initialize Anki export functionality
 */
function initAnkiExport() {
  // Create Anki button click handler
  document.getElementById('createAnkiBtn')?.addEventListener('click', function(e) {
    e.preventDefault();
    openAnkiExportModal();
  });

  // Export button click handler
  document.getElementById('exportAnkiBtn')?.addEventListener('click', function(e) {
    e.preventDefault();
    exportAnkiDeck();
  });

  // Update preview when options change
  const previewElements = ['includePronunciation', 'includeExamples'];
  previewElements.forEach(id => {
    document.getElementById(id)?.addEventListener('change', updateAnkiPreview);
  });
}

/**
 * Open the Anki export modal and initialize settings
 */
function openAnkiExportModal() {
  // Get selected word IDs from the word selection module
  const selectedWordIds = window.wordSelection?.getSelectedWordIds() || [];

  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word to create cards', 'warning');
    return;
  }

  // Update word count
  const wordCountElement = document.getElementById('ankiSelectedWordsCount');
  if (wordCountElement) {
    wordCountElement.textContent = `Selected words: ${selectedWordIds.length}`;
  }

  // Reset form to defaults
  document.getElementById('ankiExportForm')?.reset();

  // Show the modal
  const ankiModal = new bootstrap.Modal(document.getElementById('ankiExportModal'));
  ankiModal.show();

  // Update preview
  updateAnkiPreview();
}

/**
 * Update Anki card preview based on current settings
 */
function updateAnkiPreview() {
  // Get current settings
  const includePronunciation = document.getElementById('includePronunciation')?.checked || false;
  const includeExamples = document.getElementById('includeExamples')?.checked || false;

  // Update preview elements visibility
  const pronunciationElements = ['previewPronunciation', 'backPronunciation'];
  pronunciationElements.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.style.display = includePronunciation ? 'block' : 'none';
    }
  });

  const exampleElement = document.getElementById('previewExample');
  if (exampleElement) {
    exampleElement.style.display = includeExamples ? 'block' : 'none';
  }
}

/**
 * Export selected words as an Anki deck
 */
async function exportAnkiDeck() {
  // Get selected word IDs from the word selection module
  const selectedWordIds = window.wordSelection?.getSelectedWordIds() || [];

  if (selectedWordIds.length === 0) {
    showToast('Please select at least one word to create cards', 'warning');
    return;
  }

  // Get export settings from form
  const deckName = document.getElementById('deckName')?.value.trim() || 'Vocabulary';
  const cardFormat = document.querySelector('input[name="cardFormat"]:checked')?.value || 'basic';
  const includePronunciation = document.getElementById('includePronunciation')?.checked || false;
  const includeExamples = document.getElementById('includeExamples')?.checked || false;
  const updateStatus = document.getElementById('updateStatus')?.checked || false;

  // Validate settings
  if (!deckName) {
    showToast('Please enter a deck name', 'warning');
    return;
  }

  // Prepare export data
  const exportData = {
    deckName,
    cardFormat,
    includePronunciation,
    includeExamples,
    updateStatus,
    wordIds: selectedWordIds
  };

  // Update button state to show loading
  const exportBtn = document.getElementById('exportAnkiBtn');
  if (!exportBtn) return;

  const originalText = exportBtn.innerHTML;
  exportBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Creating deck...';
  exportBtn.disabled = true;

  try {
    // Call API to create deck
    const response = await fetch('/api/export-anki', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(exportData)
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${response.statusText}`);
    }

    // Get the Anki package file as blob
    const blob = await response.blob();

    // Create download link
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `${deckName}.apkg`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);

    // Close modal
    const ankiModal = bootstrap.Modal.getInstance(document.getElementById('ankiExportModal'));
    if (ankiModal) {
      ankiModal.hide();
    }

    // Show success message
    showToast(`Deck "${deckName}" has been successfully exported with ${selectedWordIds.length} words.`, 'success');

    // Update word status if requested
    if (updateStatus) {
      // Update status to "Active" (3)
      selectedWordIds.forEach(wordId => {
        if (window.updateWordStatusUI) {
          window.updateWordStatusUI(wordId, 3);
        }
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
    }
  } catch (error) {
    console.error('Error exporting Anki deck:', error);
    showToast(`Error exporting Anki deck: ${error.message}`, 'danger');
  } finally {
    // Restore button state
    exportBtn.innerHTML = originalText;
    exportBtn.disabled = false;
  }
}

/**
 * Non-recursive showToast implementation for anki-export.js
 * Replace the existing showToast function in anki-export.js with this code
 */

// Global flag to prevent recursion
window._toastInProgress = false;

function showToast(message, type = 'info', logToConsole = false) {
    // Check if we're already showing a toast to prevent recursion
    if (window._toastInProgress) {
        console.warn("Toast blocked to prevent recursion:", message);
        return;
    }

    // Set flag to prevent recursion
    window._toastInProgress = true;

    try {
        // Check if the message is one of our info texts from modals
        if (type === 'info' && (
            message.includes('A new deck will be created with') ||
            message.includes('Selected words') && message.includes('will be added to the specified deck')
        )) {
            // Just log it if requested, but don't show toast
            if (logToConsole) {
                console.log(`[${type.toUpperCase()}] ${message}`);
            }
            return;
        }

        // Only log to console for errors, warnings, or if explicitly requested
        if (logToConsole || type === 'danger' || type === 'warning') {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }

        // Create main toast container if it doesn't exist
        let toastContainer = document.querySelector('.toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(toastContainer);
        }

        // Create notification
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

        // Add to container
        toastContainer.appendChild(toast);

        // Initialize and show toast
        if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
            const bsToast = new bootstrap.Toast(toast, {
                delay: 3000,
                autohide: true
            });

            bsToast.show();

            // Remove from DOM after hiding
            toast.addEventListener('hidden.bs.toast', function () {
                toast.remove();
            });
        } else {
            // Fallback implementation if bootstrap is unavailable
            toast.style.opacity = '1';
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.5s';
                setTimeout(() => toast.remove(), 500);
            }, 3000);
        }
    } finally {
        // Always clear the flag when done, even if there's an error
        window._toastInProgress = false;
    }
}

// Initialize Anki export functionality when DOM is ready
document.addEventListener('DOMContentLoaded', initAnkiExport);

// Export functions for use in other modules
window.ankiExport = {
  openAnkiExportModal,
  exportAnkiDeck,
  updateAnkiPreview
};