/**
 * Deck Detail Page JavaScript
 * Refactored to remove Bootstrap and language dependencies
 */

// Import our custom UI implementation that replaces Bootstrap
// import { initCustomUIImplementation } from './custom-ui.js';

/**
 * Ensure API URLs are properly initialized
 */
function initializeApiUrls() {
  // Make sure window.appData exists
  if (!window.appData) {
    window.appData = {};
  }

  // Make sure apiUrls exists
  if (!window.appData.apiUrls) {
    window.appData.apiUrls = {};
  }

  // Get the deck ID from the page
  const deckId = window.appData.deckId ||
    parseInt(window.location.pathname.match(/\/decks\/(\d+)/)?.[1]) ||
    document.querySelector('[data-deck-id]')?.dataset.deckId;

  if (deckId) {
    window.appData.deckId = deckId;

    // Set API URLs if they don't exist
    if (!window.appData.apiUrls.getCardCounts) {
      window.appData.apiUrls.getCardCounts = `/srs/api/decks/${deckId}/card_counts`;
    }

    // Add new API URL for deck settings
    if (!window.appData.apiUrls.deckSettings) {
      window.appData.apiUrls.deckSettings = `/srs/api/decks/${deckId}/settings`;
    }
  }

  console.log('API URLs initialized:', window.appData.apiUrls);
}

/**
 * Setup modals properly without Bootstrap
 */
function setupModals() {
  // Process all modals
  document.querySelectorAll('.modal').forEach(modalElement => {
    // Skip if already processed
    if (modalElement._modalFixed) return;

    // Mark as processed
    modalElement._modalFixed = true;

    try {
      // Create a modal instance using our custom implementation
      const modalInstance = new customUI.Modal(modalElement, {
        backdrop: true,
        keyboard: true,
        focus: true
      });

      // Store on element for future reference
      modalElement._customModal = modalInstance;
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
            if (modalElement._customModal) {
              modalElement._customModal.show();
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

    // Initialize modal events if needed
    if (modalElement.id === 'addWordModal') {
      modalElement.addEventListener('shown.bs.modal', loadWords);
    } else if (modalElement.id === 'deckSettingsModal') {
      modalElement.addEventListener('shown.bs.modal', loadDeckSettings);
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
        if (modalElement._customModal) {
          modalElement._customModal.hide();
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
 * Main initialization function
 */
document.addEventListener('DOMContentLoaded', () => {
  // Initialize our custom UI implementation
  initCustomUIImplementation();

  // Initialize API URLs
  initializeApiUrls();

  // Initialize all components
  initCardActions();
  initAddWordModal();
  initDeckOperations();
  initDeckSettings();
  animatePageElements();

  // Fix common issues
  fixToastIssues();
  fixWordDisplay();
  setupModals();

  // Apply light theme
  document.body.classList.add('light-theme');

  // Update card counters
  updateCardCounters();
});

/**
 * Debug API endpoints to help troubleshoot issues
 */
function debugApiEndpoints() {
  console.log('Debugging API endpoints...');

  // Log application data
  console.log('App Data:', window.appData);

  // Check if deck ID is available
  const deckId = window.appData?.deckId;
  console.log('Deck ID:', deckId);

  // Try to find deck ID in DOM if not in appData
  if (!deckId) {
    const possibleDeckIdElements = [
      document.querySelector('[data-deck-id]'),
      document.querySelector('meta[name="deck-id"]'),
    ];

    for (const element of possibleDeckIdElements) {
      if (element) {
        console.log('Found deck ID in DOM:', element.dataset.deckId || element.content);
        break;
      }
    }
  }

  // Log the route we're trying to use
  const apiUrl = window.appData?.apiUrls?.getCardCounts ||
    (deckId ? `/srs/api/decks/${deckId}/card_counts` : null);

  console.log('API URL for card counts:', apiUrl);

  // Try to manually fetch from the API to see what happens
  if (apiUrl) {
    console.log('Testing API endpoint...');
    fetch(apiUrl)
      .then(response => {
        console.log('API Response Status:', response.status);
        console.log('API Response OK:', response.ok);
        return response.text(); // Get as text first to debug
      })
      .then(text => {
        console.log('API Response Text (first 100 chars):', text.substring(0, 100));
        try {
          // Try to parse as JSON to see if it's valid
          const json = JSON.parse(text);
          console.log('Valid JSON response:', json);
        } catch (e) {
          console.error('Invalid JSON response:', e);
        }
      })
      .catch(error => {
        console.error('API request failed:', error);
      });
  }
}

// --- Card Action Handlers ---

/**
 * Update card counters in the UI based on today's date
 * Only count cards that are due today or earlier
 */
function updateCardCounters() {
  // Get current date
  const today = new Date();
  today.setHours(0, 0, 0, 0);  // Set to beginning of day for comparison

  // If the backend provides today's date, use it for consistency
  const backendToday = document.querySelector('meta[name="current-date"]')?.content;
  const todayStr = backendToday || today.toISOString().split('T')[0];

  // Get the API URL for card counts
  const deckId = window.appData?.deckId;

  // Verify we have valid data before making the API call
  if (!deckId) {
    console.warn('Cannot update card counters: Missing deck ID');
    return;
  }

  // Try to get the API URL from appData, or construct a fallback
  const apiUrl = window.appData?.apiUrls?.getCardCounts || `/srs/api/decks/${deckId}/card_counts`;

  // Fetch card counts from the API
  fetch(apiUrl)
    .then(response => {
      // Check if the response is OK before trying to parse JSON
      if (!response.ok) {
        throw new Error(`API request failed with status ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      if (data.success) {
        // Update counters for cards due today or earlier
        updateCounter('counter-new', data.counts.new);
        updateCounter('counter-learning', data.counts.learning);
        updateCounter('counter-review', data.counts.review);

        // Update visibility of review button and "no cards" message
        const totalDueCards = data.counts.new + data.counts.learning + data.counts.review;
        toggleReviewButton(totalDueCards > 0);
      } else {
        // Handle API success:false response
        console.warn('API returned success:false', data);
      }
    })
    .catch(error => {
      console.error('Error fetching card counts:', error);

      // Fallback - just show the counts as they appear in the HTML
      // This assumes the server rendered the initial counts correctly
      const newCount = document.querySelector('.counter-new')?.textContent || '0';
      const learningCount = document.querySelector('.counter-learning')?.textContent || '0';
      const reviewCount = document.querySelector('.counter-review')?.textContent || '0';

      // Calculate total based on what's already in the DOM
      const totalDueCards = parseInt(newCount) + parseInt(learningCount) + parseInt(reviewCount);
      toggleReviewButton(totalDueCards > 0);
    });
}

/**
 * Update a counter element with the given value
 */
function updateCounter(counterClass, value) {
  const counterElement = document.querySelector(`.${counterClass}`);
  if (counterElement) {
    counterElement.textContent = value;
  }
}

/**
 * Toggle visibility of review button and "no cards" message
 */
function toggleReviewButton(hasCards) {
  const reviewBtn = document.querySelector('.start-review-btn');
  const noCardsMessage = document.querySelector('.no-cards-message');

  if (reviewBtn && noCardsMessage) {
    if (hasCards) {
      reviewBtn.parentElement.style.display = 'block';
      noCardsMessage.style.display = 'none';
    } else {
      reviewBtn.parentElement.style.display = 'none';
      noCardsMessage.style.display = 'block';
    }
  }
}

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
    window.translate('resetProgress'),
    window.translate('confirmResetCardProgress'),
    window.translate('reset'),
    () => {
      if (!window.appData || !window.appData.apiUrls) {
        console.error('API URLs not defined');
        showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');
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
        if (!response.ok) throw new Error(window.translate('failedToResetProgress'));
        return response.json();
      })
      .then(data => {
        if (data.success) {
          showToast(window.translate('success'), window.translate('cardProgressReset'), 'success');
          reloadPage();
        } else {
          throw new Error(data.error || window.translate('failedToResetProgress'));
        }
      })
      .catch(error => {
        console.error('Error resetting card:', error);
        showToast(window.translate('error'), error.message, 'danger');
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
    window.translate('removeCard'),
    window.translate('confirmRemoveCard'),
    window.translate('remove'),
    () => {
      if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.deleteCard) {
        console.error('Delete card API URL not defined');
        showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');
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
          if (!response.ok) throw new Error(window.translate('failedToRemoveCard'));
          return response.json();
        })
        .then(data => {
          if (data.success) {
            showToast(window.translate('success'), window.translate('cardRemoved'), 'success');

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
            throw new Error(data.error || window.translate('failedToRemoveCard'));
          }
        })
        .catch(error => {
          console.error('Error removing card:', error);
          showToast(window.translate('error'), error.message, 'danger');
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
  select.innerHTML = `<option value="" disabled selected>${window.translate('loadingDecks')}</option>`;
  select.disabled = true;

  // Load available decks
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.getDecks) {
    console.error('Get decks API URL not defined');
    showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');
    return;
  }

  fetch(window.appData.apiUrls.getDecks)
    .then(response => {
      if (!response.ok) throw new Error(window.translate('failedToLoadDecks'));
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
          select.innerHTML = `<option value="" disabled selected>${window.translate('noOtherDecksAvailable')}</option>`;
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
          if (modalElement._customModal) {
            modalElement._customModal.show();
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
          console.error('Error showing modal:', error);
          // Fallback to manual display
          modalElement.classList.add('show');
          modalElement.style.display = 'block';
          document.body.classList.add('modal-open');
        }
      } else {
        throw new Error(data.error || window.translate('failedToLoadDecks'));
      }
    })
    .catch(error => {
      console.error('Error loading decks:', error);
      showToast(window.translate('error'), error.message, 'danger');
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
    showToast(window.translate('error'), window.translate('selectTargetDeck'), 'warning');
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
  confirmBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${window.translate('moving')}...`;

  // Send move request
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.moveCard) {
    console.error('Move card API URL not defined');
    showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');

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
      if (!response.ok) throw new Error(window.translate('failedToMoveCard'));
      return response.json();
    })
    .then(data => {
      if (data.success) {
        try {
          if (modalElement._customModal) {
            modalElement._customModal.hide();
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

        showToast(window.translate('success'), window.translate('cardMoved'), 'success');

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
        throw new Error(data.error || window.translate('failedToMoveCard'));
      }
    })
    .catch(error => {
      console.error('Error moving card:', error);
      showToast(window.translate('error'), error.message, 'danger');

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
          <span class="visually-hidden">${window.translate('loading')}</span>
        </div>
        <span class="ms-2">${window.translate('loadingWords')}</span>
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
          ${window.translate('appConfigMissing')}
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
      if (!response.ok) throw new Error(window.translate('failedToLoadWords'));
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
              ${window.translate('noWordsFound')}
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
            ${window.translate('failedToLoadWords')}
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
    showToast(window.translate('warning'), window.translate('selectAtLeastOneWord'), 'warning');
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
  addBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${window.translate('adding')}...`;

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.addCard) {
    console.error('Add card API URL not defined');
    showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');

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
      if (!response.ok) throw new Error(`${window.translate('failedToAddWord')} ${wordId}`);
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
          if (modalElement._customModal) {
            modalElement._customModal.hide();
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
      showToast(window.translate('success'), `${window.translate('added')} ${selectedWords.length} ${window.translate('wordsToDeck')}`, 'success');

      // Reload page
      reloadPage();
    })
    .catch(error => {
      console.error('Error adding words:', error);
      showToast(window.translate('error'), error.message, 'danger');

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
  const deleteDeckBtn = document.querySelector('[data-bs-target="#deleteDeckModal"]');
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
    showToast(window.translate('warning'), window.translate('deckNameRequired'), 'warning');
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
  saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${window.translate('saving')}...`;

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.updateDeck) {
    console.error('Update deck API URL not defined');
    showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');

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
      if (!response.ok) throw new Error(window.translate('failedToUpdateDeck'));
      return response.json();
    })
    .then(data => {
      if (data.success) {
        const modalElement = document.getElementById('editDeckModal');
        if (modalElement) {
          try {
            if (modalElement._customModal) {
              modalElement._customModal.hide();
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

        showToast(window.translate('success'), window.translate('deckUpdated'), 'success');
        reloadPage();
      } else {
        throw new Error(data.error || window.translate('failedToUpdateDeck'));
      }
    })
    .catch(error => {
      console.error('Error updating deck:', error);
      showToast(window.translate('error'), error.message, 'danger');

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
  deleteBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${window.translate('deleting')}...`;

  // Check if API URLs are defined
  if (!window.appData || !window.appData.apiUrls || !window.appData.apiUrls.deleteDeck) {
    console.error('Delete deck API URL not defined');
    showToast(window.translate('error'), window.translate('appConfigMissing'), 'danger');

    // Reset button
    deleteBtn.disabled = false;
    deleteBtn.innerHTML = originalBtnText;
    return;
  }

  fetch(window.appData.apiUrls.deleteDeck, { method: 'DELETE' })
    .then(response => {
      if (!response.ok) throw new Error(window.translate('failedToDeleteDeck'));
      return response.json();
    })
    .then(data => {
      if (data.success) {
        showToast(window.translate('success'), window.translate('deckDeleted'), 'success');
        // Redirect to decks list
        if (window.appData && window.appData.urls && window.appData.urls.decksList) {
          window.location.href = window.appData.urls.decksList;
        } else {
          window.location.href = '/decks/';
        }
      } else {
        throw new Error(data.error || window.translate('failedToDeleteDeck'));
      }
    })
    .catch(error => {
      console.error('Error deleting deck:', error);
      showToast(window.translate('error'), error.message, 'danger');

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
  // For now, use simple browser confirm
  if (confirm(message)) {
    onConfirm();
  }

  // More advanced implementation would create a modal dynamically
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

  // Check if toast container exists, if not create it
  let toastContainer = document.querySelector('.toast-container');

  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }

  // Create toast element
  const toastElement = document.createElement('div');
  toastElement.className = `toast align-items-center text-white bg-${type} border-0`;
  toastElement.setAttribute('role', 'alert');
  toastElement.setAttribute('aria-live', 'assertive');
  toastElement.setAttribute('aria-atomic', 'true');
  toastElement.dataset.autoRemove = 'true';

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

  // Initialize and show toast using our custom implementation
  try {
    const toast = new customUI.Toast(toastElement, { autohide: true, delay: 5000 });
    toast.show();
  } catch (error) {
    console.error('Error showing toast:', error);
    // Fallback - just append and remove after delay
    toastElement.classList.add('show');
    setTimeout(() => {
      toastElement.classList.remove('show');
      setTimeout(() => toastElement.remove(), 300);
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
      toast.remove();
    } catch (e) {
      console.error('Error removing toast:', e);
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
      if (!response.ok) throw new Error(window.translate('failedToLoadWords'));
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
        wordLink.textContent = word.english_word || window.translate('unknownWord');
      }

      // Update translation if present
      const translationCell = row.querySelector('td:nth-child(2)');
      if (translationCell && word.russian_word) {
        translationCell.textContent = word.russian_word;
      }
    }
  });
}

// --- Deck Settings ---

/**
 * Initialize deck settings functionality
 */
function initDeckSettings() {
  // Initialize tooltips
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(tooltip => {
    tooltip.title = tooltip.dataset.bsTitle || tooltip.title;

    // Create simple tooltip show/hide behavior
    tooltip.addEventListener('mouseenter', () => {
      let tooltipElement = document.getElementById(`tooltip-${tooltip.id}`);

      if (!tooltipElement) {
        tooltipElement = document.createElement('div');
        tooltipElement.id = `tooltip-${tooltip.id}`;
        tooltipElement.className = 'tooltip show';
        tooltipElement.innerHTML = `<div class="tooltip-inner">${tooltip.title}</div>`;
        document.body.appendChild(tooltipElement);
      }

      const rect = tooltip.getBoundingClientRect();
      tooltipElement.style.top = `${rect.top - tooltipElement.offsetHeight - 5}px`;
      tooltipElement.style.left = `${rect.left + rect.width / 2 - tooltipElement.offsetWidth / 2}px`;
      tooltipElement.style.display = 'block';
    });

    tooltip.addEventListener('mouseleave', () => {
      const tooltipElement = document.getElementById(`tooltip-${tooltip.id}`);
      if (tooltipElement) {
        tooltipElement.style.display = 'none';
      }
    });
  });

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
  showToast(window.translate('settingsReset'), `${window.translate('reset')} ${window.translate(setting)} ${window.translate('toDefaultValue')}`, 'info');
}

/**
 * Load deck settings - BYPASS VERSION
 * Uses default settings without API call to avoid server errors
 */
function loadDeckSettings() {
  console.log('BYPASS: Loading default deck settings without API call');

  // Immediately apply default settings
  const defaultSettings = getDefaultDeckSettings();
  applySettingsToForm(defaultSettings);

  // Add a maintenance notice to the settings dialog
  const settingsContainer = document.querySelector('.modal-body');
  if (settingsContainer) {
    const infoAlert = document.createElement('div');
    infoAlert.className = 'alert alert-warning mb-3';
    infoAlert.innerHTML = `
      <i class="bi bi-gear me-2"></i>
      <strong>Settings are in maintenance mode.</strong> Changes will be visible in the interface but not saved to the server.
    `;

    // Insert at the top of the settings container
    if (settingsContainer.firstChild) {
      settingsContainer.insertBefore(infoAlert, settingsContainer.firstChild);
    } else {
      settingsContainer.appendChild(infoAlert);
    }
  }
}

/**
 * Save deck settings - BYPASS VERSION
 * Simulates a successful save operation without making API call
 */
function saveDeckSettings() {
  console.log('BYPASS: Simulating settings save');

  // Close modal
  const modalElement = document.getElementById('deckSettingsModal');
  if (modalElement) {
    try {
      if (modalElement._customModal) {
        modalElement._customModal.hide();
      } else {
        // Fallback to manual hiding
        modalElement.classList.remove('show');
        modalElement.style.display = 'none';
        document.body.classList.remove('modal-open');
        document.querySelector('.modal-backdrop')?.remove();
      }
    } catch (error) {
      // Force hide
      modalElement.style.display = 'none';
      document.querySelector('.modal-backdrop')?.remove();
    }
  }

  // Show informative toast
  showToast(
    window.translate('notice') || 'Notice',
    'Settings displayed in maintenance mode. Changes will be visible in the interface but not saved permanently.',
    'info'
  );

  // Log what settings would have been saved
  const formData = {
    new_cards_per_day: parseInt(document.getElementById('newCardsValue')?.value || "20"),
    reviews_per_day: parseInt(document.getElementById('maxReviewsValue')?.value || "200"),
    // Add other fields as needed for debugging
  };

  console.log('Settings that would be saved:', formData);
}

/**
 * Get default deck settings
 * @returns {Object} Default settings object
 */
function getDefaultDeckSettings() {
  return {
    new_cards_per_day: 20,
    reviews_per_day: 200,
    learning_steps: '1m 10m',
    graduating_interval: 1,
    easy_interval: 4,
    insertion_order: 'sequential',
    relearning_steps: '10m',
    minimum_interval: 1,
    lapse_threshold: 8,
    lapse_action: 'tag',
    new_card_gathering: 'deck',
    new_card_order: 'cardType',
    new_review_mix: 'mix',
    inter_day_order: 'mix',
    review_order: 'dueRandom',
    bury_new_related: false,
    bury_reviews_related: false,
    bury_interday: false,
    max_answer_time: 60,
    show_answer_timer: true,
    stop_timer_on_answer: false,
    seconds_show_question: 0.0,
    seconds_show_answer: 0.0,
    wait_for_audio: false,
    answer_action: 'bury',
    disable_auto_play: false,
    skip_question_audio: false,
    fsrs_enabled: true,
    max_interval: 36500,
    starting_ease: 2.5,
    easy_bonus: 1.3,
    interval_modifier: 1.0,
    hard_interval: 1.2,
    new_interval: 0.0
  };
}

/**
 * Apply settings object to form controls
 * @param {Object} settings - Settings object
 */
function applySettingsToForm(settings) {
  // Daily limits
  const newCardsRange = document.getElementById('newCardsRange');
  const newCardsValue = document.getElementById('newCardsValue');

  if (newCardsRange) newCardsRange.value = settings.new_cards_per_day;
  if (newCardsValue) newCardsValue.value = settings.new_cards_per_day;

  const newCardsOption = document.getElementById('newCardsPreset');
  if (newCardsOption) newCardsOption.checked = true;

  const maxReviewsRange = document.getElementById('maxReviewsRange');
  const maxReviewsValue = document.getElementById('maxReviewsValue');

  if (maxReviewsRange) maxReviewsRange.value = settings.reviews_per_day;
  if (maxReviewsValue) maxReviewsValue.value = settings.reviews_per_day;

  const maxReviewsOption = document.getElementById('maxReviewsPreset');
  if (maxReviewsOption) maxReviewsOption.checked = true;

  // Learning steps
  const learningSteps = document.getElementById('learningSteps');
  if (learningSteps) learningSteps.value = settings.learning_steps;

  const graduatingInterval = document.getElementById('graduatingInterval');
  if (graduatingInterval) graduatingInterval.value = settings.graduating_interval;

  const easyInterval = document.getElementById('easyInterval');
  if (easyInterval) easyInterval.value = settings.easy_interval;

  const insertionOrder = document.getElementById('insertionOrder');
  if (insertionOrder) {
    for (let i = 0; i < insertionOrder.options.length; i++) {
      if (insertionOrder.options[i].value === settings.insertion_order) {
        insertionOrder.selectedIndex = i;
        break;
      }
    }
  }

  // Forgotten cards
  const relearningSteps = document.getElementById('relearningSteps');
  if (relearningSteps) relearningSteps.value = settings.relearning_steps;

  const minLapseInterval = document.getElementById('minLapseInterval');
  if (minLapseInterval) minLapseInterval.value = settings.minimum_interval;

  const lapseThreshold = document.getElementById('lapseThreshold');
  if (lapseThreshold) lapseThreshold.value = settings.lapse_threshold;

  const lapseAction = document.getElementById('lapseAction');
  if (lapseAction) {
    for (let i = 0; i < lapseAction.options.length; i++) {
      if (lapseAction.options[i].value === settings.lapse_action) {
        lapseAction.selectedIndex = i;
        break;
      }
    }
  }

  // Order settings
  const newCardGathering = document.getElementById('newCardGathering');
  if (newCardGathering) {
    for (let i = 0; i < newCardGathering.options.length; i++) {
      if (newCardGathering.options[i].value === settings.new_card_gathering) {
        newCardGathering.selectedIndex = i;
        break;
      }
    }
  }

  const newCardSort = document.getElementById('newCardSort');
  if (newCardSort) {
    for (let i = 0; i < newCardSort.options.length; i++) {
      if (newCardSort.options[i].value === settings.new_card_order) {
        newCardSort.selectedIndex = i;
        break;
      }
    }
  }

  const newReviewMix = document.getElementById('newReviewMix');
  if (newReviewMix) {
    for (let i = 0; i < newReviewMix.options.length; i++) {
      if (newReviewMix.options[i].value === settings.new_review_mix) {
        newReviewMix.selectedIndex = i;
        break;
      }
    }
  }

  const interDayOrder = document.getElementById('interDayOrder');
  if (interDayOrder) {
    for (let i = 0; i < interDayOrder.options.length; i++) {
      if (interDayOrder.options[i].value === settings.inter_day_order) {
        interDayOrder.selectedIndex = i;
        break;
      }
    }
  }

  const reviewOrder = document.getElementById('reviewOrder');
  if (reviewOrder) {
    for (let i = 0; i < reviewOrder.options.length; i++) {
      if (reviewOrder.options[i].value === settings.review_order) {
        reviewOrder.selectedIndex = i;
        break;
      }
    }
  }

  // Burying options
  const buryNewRelated = document.getElementById('buryNewRelated');
  if (buryNewRelated) buryNewRelated.checked = settings.bury_new_related;

  const buryReviewsRelated = document.getElementById('buryReviewsRelated');
  if (buryReviewsRelated) buryReviewsRelated.checked = settings.bury_reviews_related;

  const buryInterday = document.getElementById('buryInterday');
  if (buryInterday) buryInterday.checked = settings.bury_interday;

  // Timer settings
  const maxAnswerTime = document.getElementById('maxAnswerTime');
  if (maxAnswerTime) maxAnswerTime.value = settings.max_answer_time;

  const showAnswerTimer = document.getElementById('showAnswerTimer');
  if (showAnswerTimer) showAnswerTimer.checked = settings.show_answer_timer;

  const stopTimerOnAnswer = document.getElementById('stopTimerOnAnswer');
  if (stopTimerOnAnswer) stopTimerOnAnswer.checked = settings.stop_timer_on_answer;

  const secondsShowQuestion = document.getElementById('secondsShowQuestion');
  if (secondsShowQuestion) secondsShowQuestion.value = settings.seconds_show_question;

  const secondsShowAnswer = document.getElementById('secondsShowAnswer');
  if (secondsShowAnswer) secondsShowAnswer.value = settings.seconds_show_answer;

  const waitForAudio = document.getElementById('waitForAudio');
  if (waitForAudio) waitForAudio.checked = settings.wait_for_audio;

  const answerAction = document.getElementById('answerAction');
  if (answerAction) {
    for (let i = 0; i < answerAction.options.length; i++) {
      if (answerAction.options[i].value === settings.answer_action) {
        answerAction.selectedIndex = i;
        break;
      }
    }
  }

  // Audio settings
  const disableAutoPlay = document.getElementById('disableAutoPlay');
  if (disableAutoPlay) disableAutoPlay.checked = settings.disable_auto_play;

  const skipQuestionAudio = document.getElementById('skipQuestionAudio');
  if (skipQuestionAudio) skipQuestionAudio.checked = settings.skip_question_audio;

  // Advanced settings
  const fsrsEnabled = document.getElementById('fsrsEnabled');
  if (fsrsEnabled) fsrsEnabled.checked = settings.fsrs_enabled;

  const maxInterval = document.getElementById('maxInterval');
  if (maxInterval) maxInterval.value = settings.max_interval;

  const startingEase = document.getElementById('startingEase');
  if (startingEase) startingEase.value = settings.starting_ease;

  const easyBonus = document.getElementById('easyBonus');
  if (easyBonus) easyBonus.value = settings.easy_bonus;

  const intervalModifier = document.getElementById('intervalModifier');
  if (intervalModifier) intervalModifier.value = settings.interval_modifier;

  const hardInterval = document.getElementById('hardInterval');
  if (hardInterval) hardInterval.value = settings.hard_interval;

  const newInterval = document.getElementById('newInterval');
  if (newInterval) newInterval.value = settings.new_interval;
}