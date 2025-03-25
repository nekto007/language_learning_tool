/**
 * Deck Detail Page JavaScript
 * Handles deck management, card operations and API interactions
 */

// Fix for Bootstrap modal issues
(function() {
  // Initialize a backup object if bootstrap is missing
  if (typeof bootstrap === 'undefined') {
    console.warn('Bootstrap not found - initializing backup implementation');
    window.bootstrap = {
      Modal: function(element, config) {
        this.element = element;
        this._config = config || { backdrop: true, keyboard: true, focus: true };

        // Simple show method
        this.show = function() {
          this.element.classList.add('show');
          this.element.style.display = 'block';
          document.body.classList.add('modal-open');

          // Add backdrop
          if (this._config.backdrop !== false && !document.querySelector('.modal-backdrop')) {
            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            document.body.appendChild(backdrop);
          }
        };

        // Simple hide method
        this.hide = function() {
          this.element.classList.remove('show');
          this.element.style.display = 'none';
          document.body.classList.remove('modal-open');

          // Remove backdrop
          const backdrop = document.querySelector('.modal-backdrop');
          if (backdrop) {
            backdrop.remove();
          }
        };
      }
    };

    // Add getInstance method
    bootstrap.Modal.getInstance = function(element) {
      return element._bsModal || null;
    };
  }

  // Fix for missing _config.backdrop
  const originalModalShow = bootstrap.Modal.prototype.show;
  if (originalModalShow) {
    bootstrap.Modal.prototype.show = function() {
      // Fix missing _config
      if (!this._config) {
        this._config = { backdrop: true, keyboard: true, focus: true };
      }
      // Call original method
      try {
        originalModalShow.call(this);
      } catch (error) {
        console.error('Error in bootstrap Modal show:', error);
        // Fallback implementation
        this.element.classList.add('show');
        this.element.style.display = 'block';
        document.body.classList.add('modal-open');
      }
    };
  }
})();

// Fix any existing modal issues
function fixBootstrapModalIssues() {
  // Locate all modals
  document.querySelectorAll('.modal').forEach(modalElement => {
    // Skip if already processed
    if (modalElement._bsModalFixed) return;

    // Mark as processed
    modalElement._bsModalFixed = true;

    try {
      // Create a proper Bootstrap Modal instance
      const modalInstance = new bootstrap.Modal(modalElement, {
        backdrop: true,
        keyboard: true,
        focus: true
      });

      // Store on element for future reference
      modalElement._bsModal = modalInstance;
    } catch (error) {
      console.error(`Error initializing modal ${modalElement.id}:`, error);
    }
  });
}

// Call immediately to fix any issues with existing modals
fixBootstrapModalIssues();

document.addEventListener('DOMContentLoaded', () => {
  // Initialize all components
  initCardActions();
  initAddWordModal();
  initDeckOperations();
  initDeckSettings();
  animatePageElements();

  // Add these new fixes
  fixToastIssues();
  fixWordDisplay();
  setupModals();

  // Apply light theme
  enforceLightTheme();

  // Reapply styles after a delay to ensure they override any late-loading styles
  setTimeout(enforceLightTheme, 100);
  setTimeout(enforceLightTheme, 500);
  setTimeout(enforceLightTheme, 1000);
});

// --- Card Action Handlers ---

/**
 * Initialize card action buttons
 */
function initCardActions() {
  // Move card buttons
  document.querySelectorAll('.move-card-btn').forEach(btn => {
    btn.addEventListener('click', event => {
      const cardId = event.currentTarget.dataset.cardId;
      openMoveCardModal(cardId);
    });
  });

  // Reset card progress buttons
  document.querySelectorAll('.reset-card-btn').forEach(btn => {
    btn.addEventListener('click', event => {
      const cardId = event.currentTarget.dataset.cardId;
      resetCardProgress(cardId);
    });
  });

  // Remove card buttons
  document.querySelectorAll('.remove-card-btn').forEach(btn => {
    btn.addEventListener('click', event => {
      const cardId = event.currentTarget.dataset.cardId;
      // Set deletion flag
      window.explicitlyRequestedDeletion = true;
      removeCardFromDeck(cardId);
    });
  });

  // Move card confirmation
  const confirmMoveCardBtn = document.getElementById('confirmMoveCardBtn');
  if (confirmMoveCardBtn) {
    confirmMoveCardBtn.addEventListener('click', confirmMoveCard);
  }
}

/**
 * Reset a card's learning progress
 * @param {string} cardId - ID of the card to reset
 */
function resetCardProgress(cardId) {
  if (!cardId) return;

  showConfirmationDialog(
    'Reset Progress',
    'Are you sure you want to reset the learning progress for this card?',
    'Reset',
    () => {
      if (!window.appData || !window.appData.apiUrls) {
        console.error('API URLs not defined');
        showToast('Error', 'Application configuration is missing', 'danger');
        return;
      }

      const url = window.appData.apiUrls.reviewCard.replace('0', cardId);

      // Show loading state
      const cardRow = document.querySelector(`tr[data-card-id="${cardId}"]`);
      if (cardRow) {
        cardRow.classList.add('table-warning', 'loading-pulse');
      }

      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ difficulty: 'hard' })
      })
      .then(response => {
        if (!response.ok) throw new Error('Failed to reset card progress');
        return response.json();
      })
      .then(data => {
        if (data.success) {
          showToast('Success', 'Card progress has been reset', 'success');
          reloadPage();
        } else {
          throw new Error(data.error || 'Failed to reset card progress');
        }
      })
      .catch(error => {
        console.error('Error resetting card:', error);
        showToast('Error', error.message, 'danger');
        // Remove loading state
        if (cardRow) {
          cardRow.classList.remove('table-warning', 'loading-pulse');
        }
      });
    }
  );
}

/**
 * Remove a card from the deck
 * @param {string} cardId - ID of the card to remove
 */
function removeCardFromDeck(cardId) {
  if (!cardId) return;

  showConfirmationDialog(
    'Remove Card',
    'Are you sure you want to remove this card from the deck?',
    'Remove',
    () => {
      if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.deleteCard) {
        console.error('Delete card API URL not defined');
        showToast('Error', 'Application configuration is missing', 'danger');
        return;
      }

      const url = window.appData.apiUrls.deleteCard.replace('0', cardId);

      // Show loading state
      const cardRow = document.querySelector(`tr[data-card-id="${cardId}"]`);
      if (cardRow) {
        cardRow.classList.add('table-danger', 'loading-pulse');
      }

      fetch(url, { method: 'DELETE' })
        .then(response => {
          if (!response.ok) throw new Error('Failed to remove card');
          return response.json();
        })
        .then(data => {
          if (data.success) {
            showToast('Success', 'Card has been removed from the deck', 'success');

            // Animate row removal
            if (cardRow) {
              cardRow.style.transition = 'all 0.5s ease';
              cardRow.style.height = '0';
              cardRow.style.opacity = '0';
              setTimeout(() => {
                cardRow.remove();

                // Check if table is empty
                const tableBody = document.querySelector('tbody');
                if (tableBody && tableBody.children.length === 0) {
                  reloadPage(); // Reload to show empty state
                }
              }, 500);
            } else {
              reloadPage();
            }
          } else {
            throw new Error(data.error || 'Failed to remove card');
          }
        })
        .catch(error => {
          console.error('Error removing card:', error);
          showToast('Error', error.message, 'danger');
          // Remove loading state
          if (cardRow) {
            cardRow.classList.remove('table-danger', 'loading-pulse');
          }
        });
    }
  );
}

/**
 * Open the move card modal and load available decks
 * @param {string} cardId - ID of the card to move
 */
function openMoveCardModal(cardId) {
  if (!cardId) return;

  // Store card ID for confirmation
  window.currentCardId = cardId;

  // Get the modal
  const modalElement = document.getElementById('moveCardModal');
  const select = document.getElementById('targetDeckSelect');

  if (!modalElement || !select) {
    console.error('Modal elements not found');
    return;
  }

  // Show loading state in select
  select.innerHTML = '<option value="" disabled selected>Loading decks...</option>';
  select.disabled = true;

  // Load available decks
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.getDecks) {
    console.error('Get decks API URL not defined');
    showToast('Error', 'Application configuration is missing', 'danger');
    return;
  }

  fetch(window.appData.apiUrls.getDecks)
    .then(response => {
      if (!response.ok) throw new Error('Failed to load decks');
      return response.json();
    })
    .then(data => {
      if (data.success && data.decks) {
        // Reset select
        select.innerHTML = '';
        select.disabled = false;

        let hasOptions = false;

        // Add deck options
        data.decks.forEach(deck => {
          // Skip current deck
          if (deck.id !== window.appData.deckId) {
            const option = document.createElement('option');
            option.value = deck.id;
            option.textContent = deck.name;
            select.appendChild(option);
            hasOptions = true;
          }
        });

        // Handle no available decks
        if (!hasOptions) {
          select.innerHTML = '<option value="" disabled selected>No other decks available</option>';
          const confirmBtn = document.getElementById('confirmMoveCardBtn');
          if (confirmBtn) {
            confirmBtn.disabled = true;
          }
        } else {
          const confirmBtn = document.getElementById('confirmMoveCardBtn');
          if (confirmBtn) {
            confirmBtn.disabled = false;
          }
        }

        // Show modal
        try {
          if (modalElement._bsModal) {
            modalElement._bsModal.show();
          } else {
            const modalInstance = new bootstrap.Modal(modalElement, {
              backdrop: true,
              keyboard: true
            });

            modalElement._bsModal = modalInstance;
            modalInstance.show();
          }
        } catch (error) {
          console.error('Error showing modal:', error);
          // Fallback to manual display
          modalElement.classList.add('show');
          modalElement.style.display = 'block';
          document.body.classList.add('modal-open');
        }
      } else {
        throw new Error(data.error || 'Failed to load decks');
      }
    })
    .catch(error => {
      console.error('Error loading decks:', error);
      showToast('Error', error.message, 'danger');
    });
}

/**
 * Confirm moving a card to another deck
 */
function confirmMoveCard() {
  const targetDeckSelect = document.getElementById('targetDeckSelect');
  if (!targetDeckSelect) {
    console.error('Target deck select not found');
    return;
  }

  const targetDeckId = targetDeckSelect.value;
  const cardId = window.currentCardId;

  if (!targetDeckId || !cardId) {
    showToast('Error', 'Please select a target deck', 'warning');
    return;
  }

  // Get the modal to close it later
  const modalElement = document.getElementById('moveCardModal');
  if (!modalElement) {
    console.error('Move card modal not found');
    return;
  }

  // Show loading state
  const confirmBtn = document.getElementById('confirmMoveCardBtn');
  if (!confirmBtn) {
    console.error('Confirm button not found');
    return;
  }

  const originalBtnText = confirmBtn.innerHTML;
  confirmBtn.disabled = true;
  confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Moving...';

  // Send move request
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.moveCard) {
    console.error('Move card API URL not defined');
    showToast('Error', 'Application configuration is missing', 'danger');

    // Reset button
    confirmBtn.disabled = false;
    confirmBtn.innerHTML = originalBtnText;
    return;
  }

  const url = window.appData.apiUrls.moveCard.replace('0', cardId);

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck_id: targetDeckId })
  })
    .then(response => {
      if (!response.ok) throw new Error('Failed to move card');
      return response.json();
    })
    .then(data => {
      if (data.success) {
        try {
          if (modalElement._bsModal) {
            modalElement._bsModal.hide();
          } else {
            // Fallback manual close
            modalElement.classList.remove('show');
            modalElement.style.display = 'none';
            document.body.classList.remove('modal-open');
            document.querySelector('.modal-backdrop')?.remove();
          }
        } catch (error) {
          console.error('Error closing modal:', error);
          // Force hide
          modalElement.style.display = 'none';
          document.querySelector('.modal-backdrop')?.remove();
        }

        showToast('Success', 'Card has been moved to another deck', 'success');

        // Animate row removal
        const cardRow = document.querySelector(`tr[data-card-id="${cardId}"]`);
        if (cardRow) {
          cardRow.style.transition = 'all 0.5s ease';
          cardRow.style.height = '0';
          cardRow.style.opacity = '0';
          setTimeout(() => {
            cardRow.remove();

            // Check if table is empty
            const tableBody = document.querySelector('tbody');
            if (tableBody && tableBody.children.length === 0) {
              reloadPage(); // Reload to show empty state
            }
          }, 500);
        } else {
          reloadPage();
        }
      } else {
        throw new Error(data.error || 'Failed to move card');
      }
    })
    .catch(error => {
      console.error('Error moving card:', error);
      showToast('Error', error.message, 'danger');

      // Reset button
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = originalBtnText;
    });
}

// --- Add Word Modal Functionality ---

/**
 * Initialize the add word modal functionality
 */
function initAddWordModal() {
  const addWordModal = document.getElementById('addWordModal');
  if (!addWordModal) return;

  // Create a modal instance with explicit configuration
  try {
    const modalInstance = new bootstrap.Modal(addWordModal, {
      backdrop: true,
      keyboard: true,
      focus: true
    });

    // Store the instance for future use
    addWordModal._bsModal = modalInstance;
  } catch (error) {
    console.error('Error initializing add word modal:', error);
  }

  // Load words when modal is shown
  addWordModal.addEventListener('show.bs.modal', loadWords);

  // Form control event listeners
  const wordStatusSelect = document.getElementById('wordStatusSelect');
  if (wordStatusSelect) {
    wordStatusSelect.addEventListener('change', loadWords);
  }

  const wordSearchInput = document.getElementById('wordSearchInput');
  if (wordSearchInput) {
    wordSearchInput.addEventListener('input', debounce(loadWords, 300));
  }

  const selectAllWords = document.getElementById('selectAllWords');
  if (selectAllWords) {
    selectAllWords.addEventListener('change', toggleAllWords);
  }

  const addSelectedWordsBtn = document.getElementById('addSelectedWordsBtn');
  if (addSelectedWordsBtn) {
    addSelectedWordsBtn.addEventListener('click', addSelectedWords);
  }

  // Fix the "Add Words" button
  const addWordsButtons = document.querySelectorAll('[data-bs-toggle="modal"][data-bs-target="#addWordModal"]');
  addWordsButtons.forEach(btn => {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();

      try {
        if (addWordModal._bsModal) {
          addWordModal._bsModal.show();
        } else {
          // Fallback
          addWordModal.classList.add('show');
          addWordModal.style.display = 'block';
          document.body.classList.add('modal-open');

          if (!document.querySelector('.modal-backdrop')) {
            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            document.body.appendChild(backdrop);
          }
        }
      } catch (error) {
        console.error('Error showing Add Word modal:', error);
        // Last resort fallback
        addWordModal.style.display = 'block';
      }
    });
  });
}

/**
 * Load words for the add word modal
 */
function loadWords() {
  const wordStatusSelect = document.getElementById('wordStatusSelect');
  const wordSearchInput = document.getElementById('wordSearchInput');
  const wordsList = document.getElementById('wordsList');

  const status = wordStatusSelect ? wordStatusSelect.value || '' : '';
  const search = wordSearchInput ? wordSearchInput.value || '' : '';

  if (!wordsList) return;

  // Show loading state
  wordsList.innerHTML = `
    <tr id="wordsLoadingRow">
      <td colspan="3" class="text-center py-3">
        <div class="spinner-border spinner-border-sm text-primary" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
        <span class="ms-2">Loading words...</span>
      </td>
    </tr>
  `;

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.wordsList) {
    console.error('Words list API URL not defined');
    wordsList.innerHTML = `
      <tr>
        <td colspan="3" class="text-center py-3 text-danger">
          <i class="bi bi-exclamation-triangle me-2"></i>
          Application configuration is missing
        </td>
      </tr>
    `;
    return;
  }

  // Build the API URL with parameters
  let url = `${window.appData.apiUrls.wordsList}?format=json`;
  if (status) url += `&status=${status}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  // Fetch words from API
  fetch(url)
    .then(response => {
      if (!response.ok) throw new Error('Failed to load words');
      return response.json();
    })
    .then(data => {
      if (data.words && data.words.length > 0) {
        let html = '';

        data.words.forEach(word => {
          html += `
            <tr>
              <td>
                <div class="form-check">
                  <input class="form-check-input word-checkbox" type="checkbox" value="${word.id}">
                </div>
              </td>
              <td>${escapeHtml(word.english_word)}</td>
              <td>${escapeHtml(word.russian_word || '')}</td>
            </tr>
          `;
        });

        wordsList.innerHTML = html;

        // Reset select all checkbox
        const selectAllCheck = document.getElementById('selectAllWords');
        if (selectAllCheck) selectAllCheck.checked = false;
      } else {
        wordsList.innerHTML = `
          <tr>
            <td colspan="3" class="text-center py-3">
              <i class="bi bi-search me-2"></i>
              No words found
            </td>
          </tr>
        `;
      }
    })
    .catch(error => {
      console.error('Error loading words:', error);
      wordsList.innerHTML = `
        <tr>
          <td colspan="3" class="text-center py-3 text-danger">
            <i class="bi bi-exclamation-triangle me-2"></i>
            Failed to load words
          </td>
        </tr>
      `;
    });
}

/**
 * Toggle all word checkboxes
 * @param {Event} event - Change event
 */
function toggleAllWords(event) {
  const checked = event.target.checked;
  document.querySelectorAll('.word-checkbox').forEach(checkbox => {
    checkbox.checked = checked;
  });
}

/**
 * Add selected words to deck
 */
function addSelectedWords() {
  const selectedWords = Array.from(document.querySelectorAll('.word-checkbox:checked')).map(cb => cb.value);

  if (selectedWords.length === 0) {
    showToast('Warning', 'Please select at least one word', 'warning');
    return;
  }

  // Disable button and show loading state
  const addBtn = document.getElementById('addSelectedWordsBtn');
  if (!addBtn) {
    console.error('Add selected words button not found');
    return;
  }

  const originalBtnText = addBtn.innerHTML;
  addBtn.disabled = true;
  addBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Adding...';

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.addCard) {
    console.error('Add card API URL not defined');
    showToast('Error', 'Application configuration is missing', 'danger');

    // Reset button
    addBtn.disabled = false;
    addBtn.innerHTML = originalBtnText;
    return;
  }

  // Create array of promises for each word
  const promises = selectedWords.map(wordId => {
    return fetch(window.appData.apiUrls.addCard, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ word_id: wordId })
    }).then(response => {
      if (!response.ok) throw new Error(`Failed to add word ${wordId}`);
      return response.json();
    });
  });

  // Process all promises
  Promise.all(promises)
    .then(() => {
      // Close modal
      const modalElement = document.getElementById('addWordModal');
      if (modalElement) {
        try {
          if (modalElement._bsModal) {
            modalElement._bsModal.hide();
          } else {
            // Fallback to manual hiding
            modalElement.classList.remove('show');
            modalElement.style.display = 'none';
            document.body.classList.remove('modal-open');
            document.querySelector('.modal-backdrop')?.remove();
          }
        } catch (error) {
          console.error('Error closing modal:', error);
          // Force hide
          modalElement.style.display = 'none';
          document.querySelector('.modal-backdrop')?.remove();
        }
      }

      // Show success message
      showToast('Success', `Added ${selectedWords.length} words to deck`, 'success');

      // Reload page
      reloadPage();
    })
    .catch(error => {
      console.error('Error adding words:', error);
      showToast('Error', error.message, 'danger');

      // Reset button
      addBtn.disabled = false;
      addBtn.innerHTML = originalBtnText;
    });
}

// --- Deck Operations ---

/**
 * Initialize deck edit and delete operations
 */
function initDeckOperations() {
  // Edit deck button handler
  const saveDeckBtn = document.getElementById('saveDeckBtn');
  if (saveDeckBtn) {
    saveDeckBtn.addEventListener('click', saveDeckChanges);
  }

  // Delete deck button handler
  const confirmDeleteDeckBtn = document.getElementById('confirmDeleteDeckBtn');
  if (confirmDeleteDeckBtn) {
    confirmDeleteDeckBtn.addEventListener('click', deleteDeck);
  }

  // Set deletion flag when delete button is clicked
  const deleteDeckBtn = document.getElementById('deleteDeckBtn');
  if (deleteDeckBtn) {
    deleteDeckBtn.addEventListener('click', () => {
      window.explicitlyRequestedDeletion = true;
    });
  }
}

/**
 * Save deck changes (name and description)
 */
function saveDeckChanges() {
  const deckNameInput = document.getElementById('deckNameInput');
  const deckDescriptionInput = document.getElementById('deckDescriptionInput');

  if (!deckNameInput) {
    console.error('Deck name input not found');
    return;
  }

  const name = deckNameInput.value?.trim();
  const description = deckDescriptionInput ? deckDescriptionInput.value?.trim() : '';

  if (!name) {
    showToast('Warning', 'Deck name is required', 'warning');
    return;
  }

  // Show loading state
  const saveBtn = document.getElementById('saveDeckBtn');
  if (!saveBtn) {
    console.error('Save deck button not found');
    return;
  }

  const originalBtnText = saveBtn.innerHTML;
  saveBtn.disabled = true;
  saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...';

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.updateDeck) {
    console.error('Update deck API URL not defined');
    showToast('Error', 'Application configuration is missing', 'danger');

    // Reset button
    saveBtn.disabled = false;
    saveBtn.innerHTML = originalBtnText;
    return;
  }

  fetch(window.appData.apiUrls.updateDeck, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description })
  })
    .then(response => {
      if (!response.ok) throw new Error('Failed to update deck');
      return response.json();
    })
    .then(data => {
      if (data.success) {
        const modalElement = document.getElementById('editDeckModal');
        if (modalElement) {
          try {
            if (modalElement._bsModal) {
              modalElement._bsModal.hide();
            } else {
              // Fallback to manual hide
              modalElement.classList.remove('show');
              modalElement.style.display = 'none';
              document.body.classList.remove('modal-open');
              document.querySelector('.modal-backdrop')?.remove();
            }
          } catch (error) {
            console.error('Error closing modal:', error);
            // Force hide
            modalElement.style.display = 'none';
            document.querySelector('.modal-backdrop')?.remove();
          }
        }

        showToast('Success', 'Deck updated successfully', 'success');
        reloadPage();
      } else {
        throw new Error(data.error || 'Failed to update deck');
      }
    })
    .catch(error => {
      console.error('Error updating deck:', error);
      showToast('Error', error.message, 'danger');

      // Reset button
      saveBtn.disabled = false;
      saveBtn.innerHTML = originalBtnText;
    });
}

/**
 * Delete the current deck
 */
function deleteDeck() {
  // Show loading state
  const deleteBtn = document.getElementById('confirmDeleteDeckBtn');
  if (!deleteBtn) {
    console.error('Delete deck button not found');
    return;
  }

  const originalBtnText = deleteBtn.innerHTML;
  deleteBtn.disabled = true;
  deleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Deleting...';

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.deleteDeck) {
    console.error('Delete deck API URL not defined');
    showToast('Error', 'Application configuration is missing', 'danger');

    // Reset button
    deleteBtn.disabled = false;
    deleteBtn.innerHTML = originalBtnText;
    return;
  }

  fetch(window.appData.apiUrls.deleteDeck, { method: 'DELETE' })
    .then(response => {
      if (!response.ok) throw new Error('Failed to delete deck');
      return response.json();
    })
    .then(data => {
      if (data.success) {
        showToast('Success', 'Deck deleted successfully', 'success');
        // Redirect to decks list
        if (window.appData && window.appData.urls && window.appData.urls.decksList) {
          window.location.href = window.appData.urls.decksList;
        } else {
          window.location.href = '/decks/';
        }
      } else {
        throw new Error(data.error || 'Failed to delete deck');
      }
    })
    .catch(error => {
      console.error('Error deleting deck:', error);
      showToast('Error', error.message, 'danger');

      // Reset button
      deleteBtn.disabled = false;
      deleteBtn.innerHTML = originalBtnText;
    });
}

// --- Utility Functions ---

/**
 * Show a confirmation dialog
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @param {string} confirmText - Text for confirm button
 * @param {Function} onConfirm - Callback on confirmation
 */
function showConfirmationDialog(title, message, confirmText, onConfirm) {
  // Implementation depends on your preferred method
  // Option 1: Use Bootstrap modal (advanced)
  // Option 2: Use simple browser confirm (basic)
  if (confirm(message)) {
    onConfirm();
  }

  // More advanced implementation would create a Bootstrap modal dynamically
}

/**
 * Create and show a toast notification
 * @param {string} title - Toast title
 * @param {string} message - Toast message
 * @param {string} type - Toast type (success, danger, warning, info)
 */
function showToast(title, message, type = 'info') {
  // Don't show deletion warnings unless explicitly from a delete action
  if (type === 'danger' && message.includes('cannot be undone') &&
      !window.explicitlyRequestedDeletion) {
    console.log('Prevented unwanted warning toast');
    return;
  }

  // Check if Bootstrap 5 toast container exists, if not create it
  let toastContainer = document.querySelector('.toast-container');

  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(toastContainer);
  }

  // Create toast element
  const toastElement = document.createElement('div');
  toastElement.className = `toast align-items-center text-white bg-${type} border-0`;
  toastElement.setAttribute('role', 'alert');
  toastElement.setAttribute('aria-live', 'assertive');
  toastElement.setAttribute('aria-atomic', 'true');

  // Create toast content
  toastElement.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">
        <strong>${title}:</strong> ${message}
      </div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
    </div>
  `;

  // Add toast to container
  toastContainer.appendChild(toastElement);

  // Initialize and show toast
  try {
    const toast = new bootstrap.Toast(toastElement, { autohide: true, delay: 5000 });
    toast.show();
  } catch (error) {
    console.error('Error showing toast:', error);
    // Fallback - just append and remove after delay
    setTimeout(() => {
      toastElement.remove();
    }, 5000);
  }

  // Remove toast from DOM after it's hidden
  toastElement.addEventListener('hidden.bs.toast', () => {
    toastElement.remove();
  });
}

/**
 * Reload the current page
 */
function reloadPage() {
  window.location.reload();
}

/**
 * Escape HTML to prevent XSS
 * @param {string} html - String to escape
 * @returns {string} Escaped string
 */
function escapeHtml(html) {
  if (!html) return '';

  const div = document.createElement('div');
  div.textContent = html;
  return div.innerHTML;
}

/**
 * Debounce function to limit how often a function is called
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

/**
 * Animate page elements on load
 */
function animatePageElements() {
  const elements = [
    document.querySelector('.deck-header'),
    document.querySelector('.deck-study-progress'),
    document.querySelector('.active-filter'),
    document.querySelector('.deck-cards')
  ].filter(el => el !== null);

  elements.forEach((element, index) => {
    // Add animation class with delay
    setTimeout(() => {
      element.classList.add('fade-in');
    }, index * 100);
  });
}

/**
 * Fix for the unwanted warning toast
 * Prevents "This action cannot be undone" warning from showing unexpectedly
 */
function fixToastIssues() {
  // Clear any existing toast containers that might have been created
  const existingToasts = document.querySelectorAll('.toast-container .toast');
  existingToasts.forEach(toast => {
    try {
      const bsToast = bootstrap.Toast.getInstance(toast);
      if (bsToast) {
        bsToast.hide();
      }
      toast.remove();
    } catch (e) {
      console.error('Error removing toast:', e);
      // Fallback
      toast.remove();
    }
  });

  // Initialize the deletion flag
  window.explicitlyRequestedDeletion = false;
}

/**
 * Fix for the "Unknown word" display issue
 * Ensures words are properly displayed in the table
 */
function fixWordDisplay() {
  // Check if words data is properly loaded
  if (!window.appData || !window.appData.words) {
    // Fetch word data if it's missing
    fetchWordData();
  }

  // Update word display in the table
  updateWordDisplay();
}

/**
 * Fetch word data from the server
 */
function fetchWordData() {
  // Initialize words data structure if not exists
  if (!window.appData) window.appData = {};
  if (!window.appData.words) window.appData.words = {};

  // Get all word IDs from the table
  const rows = document.querySelectorAll('tr[data-card-id]');
  const wordIds = Array.from(rows).map(row => {
    return row.dataset.wordId || null;
  }).filter(id => id);

  if (wordIds.length === 0) return;

  // Check if API URLs are defined
  if (!window.appData.apiUrls || !window.appData.apiUrls.wordsList) {
    console.error('Words list API URL not defined');
    return;
  }

  // Fetch word data for these IDs
  fetch(`${window.appData.apiUrls.wordsList}?ids=${wordIds.join(',')}&format=json`)
    .then(response => {
      if (!response.ok) throw new Error('Failed to load word data');
      return response.json();
    })
    .then(data => {
      if (data.words && data.words.length > 0) {
        // Store word data
        data.words.forEach(word => {
          window.appData.words[word.id] = word;
        });
        // Update display
        updateWordDisplay();
      }
    })
    .catch(error => {
      console.error('Error loading word data:', error);
    });
}

/**
 * Update the word display in the table
 */
function updateWordDisplay() {
  // Check if words data exists
  if (!window.appData || !window.appData.words) return;

  // Get all rows with word data
  const rows = document.querySelectorAll('tr[data-card-id]');

  rows.forEach(row => {
    // Get word ID from the data attribute
    const wordId = row.dataset.wordId;
    if (!wordId) return;

    const word = window.appData.words[wordId];

    if (word) {
      // Find the word link in this row
      const wordLink = row.querySelector('.word-link');
      if (wordLink) {
        // Update word text if we have the data
        wordLink.textContent = word.english_word || 'Unknown word';
      }

      // Update translation if present
      const translationCell = row.querySelector('td:nth-child(2)');
      if (translationCell && word.russian_word) {
        translationCell.textContent = word.russian_word;
      }
    }
  });
}

/**
 * Improved modal management
 * Prevents modals from unexpectedly showing
 */
function setupModals() {
  // Process all modals
  document.querySelectorAll('.modal').forEach(modalElement => {
    // Skip if already processed
    if (modalElement._bsModalFixed) return;

    // Mark as processed
    modalElement._bsModalFixed = true;

    try {
      // Try to create a Bootstrap modal instance
      const modalInstance = new bootstrap.Modal(modalElement, {
        backdrop: true,
        keyboard: true,
        focus: true
      });

      // Store on element for future reference
      modalElement._bsModal = modalInstance;
    } catch (error) {
      console.error(`Error initializing modal ${modalElement.id}:`, error);
    }

    // Fix all triggers for this modal
    const modalId = modalElement.id;
    if (modalId) {
      document.querySelectorAll(`[data-bs-toggle="modal"][data-bs-target="#${modalId}"]`).forEach(trigger => {
        // Skip if already has a click handler
        if (trigger._modalHandlerAdded) return;
        trigger._modalHandlerAdded = true;

        trigger.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();

          try {
            // Try to use the instance
            if (modalElement._bsModal) {
              modalElement._bsModal.show();
            } else {
              // Fallback
              modalElement.classList.add('show');
              modalElement.style.display = 'block';
              document.body.classList.add('modal-open');

              if (!document.querySelector('.modal-backdrop')) {
                const backdrop = document.createElement('div');
                backdrop.className = 'modal-backdrop fade show';
                document.body.appendChild(backdrop);
              }
            }
          } catch (error) {
            console.error(`Error showing modal ${modalId}:`, error);
            // Last resort
            modalElement.style.display = 'block';
          }
        });
      });
    }
  });

  // Find close buttons
  document.querySelectorAll('[data-bs-dismiss="modal"]').forEach(closeBtn => {
    // Skip if already processed
    if (closeBtn._closeHandlerAdded) return;
    closeBtn._closeHandlerAdded = true;

    closeBtn.addEventListener('click', function(e) {
      e.preventDefault();
      const modalElement = this.closest('.modal');
      if (!modalElement) return;

      try {
        if (modalElement._bsModal) {
          modalElement._bsModal.hide();
        } else {
          // Manual fallback
          modalElement.classList.remove('show');
          modalElement.style.display = 'none';
          document.body.classList.remove('modal-open');
          document.querySelector('.modal-backdrop')?.remove();
        }
      } catch (error) {
        console.error('Error closing modal:', error);
        // Force hide
        modalElement.style.display = 'none';
        document.querySelector('.modal-backdrop')?.remove();
      }
    });
  });
}

/**
 * Function to enforce light theme consistently
 * Overrides any dark theme styling that might be applied
 */
function enforceLightTheme() {
  // Check if we're already applying theme to prevent recursion
  if (window.isApplyingTheme) {
    return;
  }

  window.isApplyingTheme = true;

  try {
    // Apply a single CSS class to body that will handle all styling
    if (!document.body.classList.contains('light-theme')) {
      document.body.classList.add('light-theme');

      // Add style tag if it doesn't exist yet
      if (!document.getElementById('light-theme-styles')) {
        const styleTag = document.createElement('style');
        styleTag.id = 'light-theme-styles';
        styleTag.textContent = `
          .light-theme {
            background-color: #f8f9fa !important;
            color: #212529 !important;
          }
          .light-theme .table {
            background-color: #ffffff !important;
            color: #212529 !important;
          }
          .light-theme .table tr {
            background-color: #ffffff !important;
            color: #212529 !important;
          }
          .light-theme .table td, .light-theme .table th {
            background-color: #ffffff !important;
            color: #212529 !important;
          }
          .light-theme .table thead th {
            background-color: #f8f9fa !important;
            color: #495057 !important;
          }
          .light-theme .card {
            background-color: #ffffff !important;
            color: #212529 !important;
            border-color: rgba(0, 0, 0, 0.125) !important;
          }
          .light-theme .card-header {
            background-color: #f8f9fa !important;
            color: #212529 !important;
          }
          .light-theme .word-link {
            color: #0d6efd !important;
          }
          .light-theme .badge.bg-primary {
            background-color: #0d6efd !important;
            color: white !important;
          }
          .light-theme .badge.bg-info {
            background-color: #0dcaf0 !important;
            color: #000 !important;
          }
          .light-theme .counter-new {
            background-color: #0dcaf0 !important;
            color: white !important;
          }
          .light-theme .counter-learning {
            background-color: #0d6efd !important;
            color: white !important;
          }
          .light-theme .counter-review {
            background-color: #198754 !important;
            color: white !important;
          }
          .light-theme .btn-primary {
            background-color: #0d6efd !important;
            border-color: #0d6efd !important;
            color: white !important;
          }
          .light-theme .btn-outline-secondary {
            color: #6c757d !important;
            border-color: #6c757d !important;
            background-color: transparent !important;
          }
        `;
        document.head.appendChild(styleTag);
      }
    }
  } catch (error) {
    console.error('Error enforcing light theme:', error);
  } finally {
    window.isApplyingTheme = false;
  }
}

/**
 * Deck Settings JavaScript
 * Handles deck settings UI interactions and saving
 */

/**
 * Initialize deck settings functionality
 */
function initDeckSettings() {
  // Initialize tooltips
  const tooltips = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  if (tooltips.length > 0) {
    try {
      tooltips.forEach(tooltip => {
        new bootstrap.Tooltip(tooltip);
      });
    } catch (error) {
      console.error('Error initializing tooltips:', error);
    }
  }

  // Sync range inputs with number inputs
  initRangeInputs();

  // Handle reset buttons
  document.querySelectorAll('.reset-to-default').forEach(btn => {
    btn.addEventListener('click', resetSettingToDefault);
  });

  // Save settings
  const saveDeckSettingsBtn = document.getElementById('saveDeckSettingsBtn');
  if (saveDeckSettingsBtn) {
    saveDeckSettingsBtn.addEventListener('click', saveDeckSettings);
  }

  // Load current settings when modal opens
  const settingsModal = document.getElementById('deckSettingsModal');
  if (settingsModal) {
    settingsModal.addEventListener('show.bs.modal', loadDeckSettings);
  }
}

/**
 * Initialize range inputs to sync with number inputs
 */
function initRangeInputs() {
  // New cards range
  const newCardsRange = document.getElementById('newCardsRange');
  const newCardsValue = document.getElementById('newCardsValue');

  if (newCardsRange && newCardsValue) {
    syncRangeWithInput(newCardsRange, newCardsValue);
  }

  // Max reviews range
  const maxReviewsRange = document.getElementById('maxReviewsRange');
  const maxReviewsValue = document.getElementById('maxReviewsValue');

  if (maxReviewsRange && maxReviewsValue) {
    syncRangeWithInput(maxReviewsRange, maxReviewsValue);
  }
}

/**
 * Sync a range input with a number input
 * @param {HTMLElement} rangeInput - Range input element
 * @param {HTMLElement} numberInput - Number input element
 */
function syncRangeWithInput(rangeInput, numberInput) {
  // Update number input when range changes
  rangeInput.addEventListener('input', () => {
    numberInput.value = rangeInput.value;
  });

  // Update range when number input changes
  numberInput.addEventListener('change', () => {
    let value = parseInt(numberInput.value);

    // Enforce min/max
    const min = parseInt(rangeInput.min);
    const max = parseInt(rangeInput.max);

    if (isNaN(value)) value = 0;
    if (value < min) value = min;
    if (value > max) value = max;

    // Update both inputs
    numberInput.value = value;
    rangeInput.value = value;
  });
}

/**
 * Reset a setting to its default value
 * @param {Event} event - Click event
 */
function resetSettingToDefault(event) {
  const setting = event.currentTarget.dataset.setting;

  // Define default values
  const defaults = {
    newCards: 20,
    maxReviews: 200
  };

  if (setting === 'newCards') {
    const newCardsRange = document.getElementById('newCardsRange');
    const newCardsValue = document.getElementById('newCardsValue');
    const newCardsPreset = document.getElementById('newCardsPreset');

    if (newCardsRange) newCardsRange.value = defaults.newCards;
    if (newCardsValue) newCardsValue.value = defaults.newCards;
    if (newCardsPreset) newCardsPreset.checked = true;
  } else if (setting === 'maxReviews') {
    const maxReviewsRange = document.getElementById('maxReviewsRange');
    const maxReviewsValue = document.getElementById('maxReviewsValue');
    const maxReviewsPreset = document.getElementById('maxReviewsPreset');

    if (maxReviewsRange) maxReviewsRange.value = defaults.maxReviews;
    if (maxReviewsValue) maxReviewsValue.value = defaults.maxReviews;
    if (maxReviewsPreset) maxReviewsPreset.checked = true;
  }

  // Show feedback
  showToast('Settings Reset', `Reset ${setting} to default value`, 'info');
}

/**
 * Load current deck settings
 */
function loadDeckSettings() {
  // In a real implementation, this would fetch current settings from server
  // For now, we'll just use hardcoded defaults

  // Example of how to load settings from server:
  /*
  const deckId = window.appData.deckId;

  fetch(`/api/decks/${deckId}/settings`)
    .then(response => response.json())
    .then(settings => {
      // Apply settings to form
      applySettingsToForm(settings);
    })
    .catch(error => {
      console.error('Error loading deck settings:', error);
      showToast('Error', 'Failed to load deck settings', 'danger');
    });
  */

  // For demo purposes, use these defaults:
  const defaultSettings = {
    newCards: {
      value: 30,
      option: 'preset'
    },
    reviews: {
      value: 300,
      option: 'preset'
    },
    reviewLimitAffectsNew: false,
    limitsStartFromTop: false,
    learningSteps: {
      again: 1,
      hard: 5,
      good: 10,
      easy: 30
    },
    graduatingInterval: 1,
    lapseSettings: {
      newInterval: 0,
      minInterval: 1
    },
    intervals: {
      easyBonus: 130,
      hardInterval: 120,
      modifier: 1.0,
      maximum: 36500
    },
    buryRelatedCards: false,
    showAnswerTimer: true
  };

  applySettingsToForm(defaultSettings);
}

/**
 * Apply settings object to form controls
 * @param {Object} settings - Settings object
 */
function applySettingsToForm(settings) {
  // Daily limits
  const newCardsRange = document.getElementById('newCardsRange');
  const newCardsValue = document.getElementById('newCardsValue');

  if (newCardsRange) newCardsRange.value = settings.newCards.value;
  if (newCardsValue) newCardsValue.value = settings.newCards.value;

  const newCardsOption = document.getElementById(`newCards${capitalizeFirstLetter(settings.newCards.option)}`);
  if (newCardsOption) newCardsOption.checked = true;

  const maxReviewsRange = document.getElementById('maxReviewsRange');
  const maxReviewsValue = document.getElementById('maxReviewsValue');

  if (maxReviewsRange) maxReviewsRange.value = settings.reviews.value;
  if (maxReviewsValue) maxReviewsValue.value = settings.reviews.value;

  const maxReviewsOption = document.getElementById(`maxReviews${capitalizeFirstLetter(settings.reviews.option)}`);
  if (maxReviewsOption) maxReviewsOption.checked = true;

  const reviewLimitAffectsNew = document.getElementById('reviewLimitAffectsNew');
  if (reviewLimitAffectsNew) reviewLimitAffectsNew.checked = settings.reviewLimitAffectsNew;

  const limitsStartFromTop = document.getElementById('limitsStartFromTop');
  if (limitsStartFromTop) limitsStartFromTop.checked = settings.limitsStartFromTop;

  // Learning options
  const againStep = document.getElementById('againStep');
  if (againStep) againStep.value = settings.learningSteps.again;

  const hardStep = document.getElementById('hardStep');
  if (hardStep) hardStep.value = settings.learningSteps.hard;

  const goodStep = document.getElementById('goodStep');
  if (goodStep) goodStep.value = settings.learningSteps.good;

  const easyStep = document.getElementById('easyStep');
  if (easyStep) easyStep.value = settings.learningSteps.easy;

  const graduatingInterval = document.getElementById('graduatingInterval');
  if (graduatingInterval) graduatingInterval.value = settings.graduatingInterval;

  const newLapseInterval = document.getElementById('newLapseInterval');
  if (newLapseInterval) newLapseInterval.value = settings.lapseSettings.newInterval;

  const minLapseInterval = document.getElementById('minLapseInterval');
  if (minLapseInterval) minLapseInterval.value = settings.lapseSettings.minInterval;

  // Scheduling
  const easyBonus = document.getElementById('easyBonus');
  if (easyBonus) easyBonus.value = settings.intervals.easyBonus;

  const hardInterval = document.getElementById('hardInterval');
  if (hardInterval) hardInterval.value = settings.intervals.hardInterval;

  const intervalModifier = document.getElementById('intervalModifier');
  if (intervalModifier) intervalModifier.value = settings.intervals.modifier;

  const maxInterval = document.getElementById('maxInterval');
  if (maxInterval) maxInterval.value = settings.intervals.maximum;

  const buryRelatedCards = document.getElementById('buryRelatedCards');
  if (buryRelatedCards) buryRelatedCards.checked = settings.buryRelatedCards;

  const showAnswerTimer = document.getElementById('showAnswerTimer');
  if (showAnswerTimer) showAnswerTimer.checked = settings.showAnswerTimer;
}

/**
 * Save deck settings
 */
function saveDeckSettings() {
  // Collect all settings from form
  const newCardsValue = document.getElementById('newCardsValue');
  const maxReviewsValue = document.getElementById('maxReviewsValue');
  const reviewLimitAffectsNew = document.getElementById('reviewLimitAffectsNew');
  const limitsStartFromTop = document.getElementById('limitsStartFromTop');
  const againStep = document.getElementById('againStep');
  const hardStep = document.getElementById('hardStep');
  const goodStep = document.getElementById('goodStep');
  const easyStep = document.getElementById('easyStep');
  const graduatingInterval = document.getElementById('graduatingInterval');
  const newLapseInterval = document.getElementById('newLapseInterval');
  const minLapseInterval = document.getElementById('minLapseInterval');
  const easyBonus = document.getElementById('easyBonus');
  const hardInterval = document.getElementById('hardInterval');
  const intervalModifier = document.getElementById('intervalModifier');
  const maxInterval = document.getElementById('maxInterval');
  const buryRelatedCards = document.getElementById('buryRelatedCards');
  const showAnswerTimer = document.getElementById('showAnswerTimer');

  const settings = {
    newCards: {
      value: newCardsValue ? parseInt(newCardsValue.value) : 20,
      option: getSelectedRadioValue('newCardsOption')
    },
    reviews: {
      value: maxReviewsValue ? parseInt(maxReviewsValue.value) : 200,
      option: getSelectedRadioValue('maxReviewsOption')
    },
    reviewLimitAffectsNew: reviewLimitAffectsNew ? reviewLimitAffectsNew.checked : false,
    limitsStartFromTop: limitsStartFromTop ? limitsStartFromTop.checked : false,
    learningSteps: {
      again: againStep ? parseInt(againStep.value) : 1,
      hard: hardStep ? parseInt(hardStep.value) : 5,
      good: goodStep ? parseInt(goodStep.value) : 10,
      easy: easyStep ? parseInt(easyStep.value) : 30
    },
    graduatingInterval: graduatingInterval ? parseInt(graduatingInterval.value) : 1,
    lapseSettings: {
      newInterval: newLapseInterval ? parseInt(newLapseInterval.value) : 0,
      minInterval: minLapseInterval ? parseInt(minLapseInterval.value) : 1
    },
    intervals: {
      easyBonus: easyBonus ? parseInt(easyBonus.value) : 130,
      hardInterval: hardInterval ? parseInt(hardInterval.value) : 120,
      modifier: intervalModifier ? parseFloat(intervalModifier.value) : 1.0,
      maximum: maxInterval ? parseInt(maxInterval.value) : 36500
    },
    buryRelatedCards: buryRelatedCards ? buryRelatedCards.checked : false,
    showAnswerTimer: showAnswerTimer ? showAnswerTimer.checked : true
  };

  // Show loading state
  const saveBtn = document.getElementById('saveDeckSettingsBtn');
  if (!saveBtn) {
    console.error('Save deck settings button not found');
    return;
  }

  const originalBtnText = saveBtn.innerHTML;
  saveBtn.disabled = true;
  saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...';

  // In a real implementation, this would save settings to server
  // For now, we'll just simulate it with a timeout

  /* Example of how to save settings to server:
  fetch(`/api/decks/${window.appData.deckId}/settings`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(settings)
  })
    .then(response => response.json())
    .then(result => {
      if (result.success) {
        bootstrap.Modal.getInstance(document.getElementById('deckSettingsModal')).hide();
        showToast('Success', 'Deck settings saved successfully', 'success');
      } else {
        throw new Error(result.error || 'Failed to save settings');
      }
    })
    .catch(error => {
      console.error('Error saving deck settings:', error);
      showToast('Error', error.message, 'danger');

      // Reset button
      saveBtn.disabled = false;
      saveBtn.innerHTML = originalBtnText;
    });
  */

  // Simulate saving
  setTimeout(() => {
    // Log settings to console for demo purposes
    console.log('Saving deck settings:', settings);

    // Close modal
    const settingsModal = document.getElementById('deckSettingsModal');
    if (settingsModal) {
      try {
        if (settingsModal._bsModal) {
          settingsModal._bsModal.hide();
        } else {
          // Fallback
          settingsModal.classList.remove('show');
          settingsModal.style.display = 'none';
          document.body.classList.remove('modal-open');
          document.querySelector('.modal-backdrop')?.remove();
        }
      } catch (error) {
        console.error('Error closing modal:', error);
        // Force hide
        settingsModal.style.display = 'none';
        document.querySelector('.modal-backdrop')?.remove();
      }
    }

    // Show success message
    showToast('Success', 'Deck settings saved successfully', 'success');

    // Reset button
    saveBtn.disabled = false;
    saveBtn.innerHTML = originalBtnText;
  }, 1000);
}

/**
 * Get the value of the selected radio button in a group
 * @param {string} name - Name of the radio button group
 * @returns {string} Value of the selected radio button
 */
function getSelectedRadioValue(name) {
  const selectedRadio = document.querySelector(`input[name="${name}"]:checked`);
  return selectedRadio ? selectedRadio.value : '';
}

/**
 * Capitalize the first letter of a string
 * @param {string} str - String to capitalize
 * @returns {string} Capitalized string
 */
function capitalizeFirstLetter(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// Setup light theme application with debouncing
window.addEventListener('load', function() {
  // Fix any Bootstrap modal issues
  fixBootstrapModalIssues();

  // Apply theme immediately on load
  enforceLightTheme();

  // Debounced reapplication of theme
  const debouncedEnforceTheme = debounce(function() {
    enforceLightTheme();
  }, 500);

  // Only observe specific new elements, not style changes
  const observer = new MutationObserver(function(mutations) {
    // Only react to childList changes (new elements), not attribute changes
    const hasNewNodes = mutations.some(mutation =>
      mutation.type === 'childList' && mutation.addedNodes.length > 0
    );

    if (hasNewNodes) {
      debouncedEnforceTheme();
    }
  });

  // Start observing only for new elements, not style changes
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: false
  });

  // Also fix modals when dynamically added
  const modalObserver = new MutationObserver(function(mutations) {
    mutations.forEach(mutation => {
      if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
        // Look for any new modals among added nodes
        mutation.addedNodes.forEach(node => {
          if (node.nodeType === 1) { // Element node
            // Check if the node itself is a modal
            if (node.classList && node.classList.contains('modal')) {
              fixBootstrapModalIssues();
            }
            // Check if it contains any modals
            if (node.querySelectorAll) {
              const modals = node.querySelectorAll('.modal');
              if (modals.length > 0) {
                fixBootstrapModalIssues();
              }
            }
          }
        });
      }
    });
  });

  // Observe for dynamic modals
  modalObserver.observe(document.body, {
    childList: true,
    subtree: true
  });
});