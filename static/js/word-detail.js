/**
 * Word Detail Page JavaScript
 * Handles audio, status changes, and deck management
 */

// Initialize the page when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  initAudioPlayer();
  initStatusButtons();
  initDeckButtons();
  initModals();
});

/**
 * Initialize custom audio player
 */
function initAudioPlayer() {
  const audioContainer = document.getElementById('audioContainer');
  const playBtn = document.getElementById('audioPlayBtn');
  const progress = document.getElementById('audioProgress');
  const progressBar = document.getElementById('audioProgressBar');
  const timeDisplay = document.getElementById('audioTime');
  const audio = document.getElementById('pronunciationAudio');

  if (!audio || !audioContainer) return;

  // Play/pause button handler
  playBtn.addEventListener('click', function() {
    if (audio.paused) {
      audio.play().catch(e => {
        console.error('Audio play error:', e);
        showToast('Error playing audio', 'danger');
      });
      playBtn.innerHTML = '<i class="bi bi-pause-fill"></i>';
    } else {
      audio.pause();
      playBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
    }
  });

  // Click on progress bar to seek
  progress.addEventListener('click', function(e) {
    const rect = this.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pos * audio.duration;
  });

  // Update progress bar and time display during playback
  audio.addEventListener('timeupdate', function() {
    const percent = (audio.currentTime / audio.duration) * 100;
    progressBar.style.width = `${percent}%`;

    // Update time display
    const currentMins = Math.floor(audio.currentTime / 60);
    const currentSecs = Math.floor(audio.currentTime % 60);
    timeDisplay.textContent = `${currentMins}:${currentSecs < 10 ? '0' : ''}${currentSecs}`;
  });

  // Reset player when audio ends
  audio.addEventListener('ended', function() {
    playBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
    progressBar.style.width = '0%';
    timeDisplay.textContent = '0:00';
  });

  // For mobile devices, preload audio on first interaction
  document.body.addEventListener('touchstart', function() {
    if (audio) {
      audio.load();
    }
  }, { once: true });
}

/**
 * Initialize status change buttons
 */
function initStatusButtons() {
  // Add event listeners using delegation
  document.addEventListener('click', function(e) {
    const statusButton = e.target.closest('.js-update-status');
    if (!statusButton) return;

    e.preventDefault();

    const wordId = statusButton.dataset.wordId;
    const statusId = statusButton.dataset.status;

    if (wordId && statusId) {
      updateWordStatus(wordId, statusId);
    }
  });

  // Make active button
  const makeActiveBtn = document.getElementById('makeActiveBtn');
  if (makeActiveBtn) {
    makeActiveBtn.addEventListener('click', function() {
      if (window.wordData && window.wordData.id) {
        updateWordStatus(window.wordData.id, 3); // 3 = Active status
      }
    });
  }
}

/**
 * Initialize deck management buttons
 */
function initDeckButtons() {
  // Add to deck button
  const addToDeckBtn = document.getElementById('addToDeckBtn');
  if (addToDeckBtn) {
    addToDeckBtn.addEventListener('click', loadDecks);
  }

  // Confirm add to deck button
  const confirmButton = document.getElementById('confirmAddToDeckBtn');
  if (confirmButton) {
    confirmButton.addEventListener('click', addToDeck);
  }

  // Remove from deck buttons
  document.addEventListener('click', function(e) {
    const removeButton = e.target.closest('.js-remove-from-deck');
    if (!removeButton) return;

    e.preventDefault();

    const cardId = removeButton.dataset.cardId;
    if (cardId) {
      removeFromDeck(cardId);
    }
  });
}

/**
 * Initialize modals
 */
function initModals() {
  // Get all elements with modal dismiss attributes
  const dismissButtons = document.querySelectorAll('[data-bs-dismiss="modal"]');

  dismissButtons.forEach(button => {
    button.addEventListener('click', function() {
      const modalId = this.closest('.modal').id;
      const modal = document.getElementById(modalId);
      if (modal) {
        modal.classList.remove('show');
      }
    });
  });

  // Close modal when clicking outside
  document.addEventListener('click', function(e) {
    const openModal = document.querySelector('.modal.show');
    if (openModal && e.target === openModal) {
      openModal.classList.remove('show');
    }
  });

  // Close modal with Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      const openModal = document.querySelector('.modal.show');
      if (openModal) {
        openModal.classList.remove('show');
      }
    }
  });
}

/**
 * Show a modal by ID
 * @param {string} modalId - The ID of the modal to show
 */
function showModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('show');

    // Focus the first input
    const firstInput = modal.querySelector('input, select, button:not([data-bs-dismiss="modal"])');
    if (firstInput) {
      setTimeout(() => {
        firstInput.focus();
      }, 100);
    }
  }
}

/**
 * Hide a modal by ID
 * @param {string} modalId - The ID of the modal to hide
 */
function hideModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('show');
  }
}

/**
 * Load available decks for the Add to Deck modal
 */
async function loadDecks() {
  if (!window.wordData || !window.wordData.apiUrls || !window.wordData.apiUrls.getDecks) {
    showToast('API URL not available', 'danger');
    return;
  }

  try {
    const response = await fetch(window.wordData.apiUrls.getDecks);
    const data = await response.json();

    if (data.success && data.decks) {
      const select = document.getElementById('deckSelect');
      select.innerHTML = '<option value="" disabled selected>Select a deck</option>';

      // Filter out decks that already contain this word
      const existingDeckIds = window.wordData.decks.map(deck => deck.id);

      data.decks.forEach(deck => {
        if (!existingDeckIds.includes(deck.id)) {
          const option = document.createElement('option');
          option.value = deck.id;
          option.textContent = deck.name;
          select.appendChild(option);
        }
      });

      // Show modal
      showModal('addToDeckModal');
    } else {
      showToast(data.error || 'Error loading decks', 'danger');
    }
  } catch (error) {
    console.error('Error loading decks:', error);
    showToast('Network error when loading decks', 'danger');
  }
}

/**
 * Add word to selected deck
 */
async function addToDeck() {
  const deckSelect = document.getElementById('deckSelect');
  if (!deckSelect || !deckSelect.value) {
    showToast('Please select a deck', 'warning');
    return;
  }

  const deckId = deckSelect.value;

  if (!window.wordData || !window.wordData.apiUrls) {
    showToast('API URL not available', 'danger');
    return;
  }

  try {
    const url = window.wordData.apiUrls.addCard.replace(':deckId', deckId);
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ word_id: window.wordData.id }),
    });

    const data = await response.json();

    if (data.success) {
      // Close modal
      hideModal('addToDeckModal');

      showToast('Word successfully added to deck', 'success');

      // Reload page after a short delay to show the toast
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } else {
      showToast(data.error || 'Failed to add word to deck', 'danger');
    }
  } catch (error) {
    console.error('Error adding word to deck:', error);
    showToast('Network error when adding to deck', 'danger');
  }
}

/**
 * Remove word from deck
 * @param {string} cardId - ID of the card to remove
 */
async function removeFromDeck(cardId) {
  if (!confirm('Are you sure you want to remove this word from the deck?')) {
    return;
  }

  if (!window.wordData || !window.wordData.apiUrls) {
    showToast('API URL not available', 'danger');
    return;
  }

  try {
    const url = window.wordData.apiUrls.deleteCard.replace(':cardId', cardId);
    const response = await fetch(url, {
      method: 'DELETE',
    });

    const data = await response.json();

    if (data.success) {
      showToast('Word removed from deck', 'success');

      // Reload page after a short delay to show the toast
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } else {
      showToast(data.error || 'Failed to remove word from deck', 'danger');
    }
  } catch (error) {
    console.error('Error removing word from deck:', error);
    showToast('Network error when removing from deck', 'danger');
  }
}

/**
 * Update word status
 * @param {string} wordId - ID of the word to update
 * @param {string} statusId - New status ID
 */
async function updateWordStatus(wordId, statusId) {
  if (!window.wordData || !window.wordData.apiUrls || !window.wordData.apiUrls.updateStatus) {
    showToast('API URL not available', 'danger');
    return;
  }

  try {
    const response = await fetch(window.wordData.apiUrls.updateStatus, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ word_id: wordId, status: statusId }),
    });

    const data = await response.json();

    if (data.success) {
      showToast('Word status updated successfully', 'success');

      // Reload page after a short delay to show the toast
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } else {
      showToast(data.error || 'Failed to update word status', 'danger');
    }
  } catch (error) {
    console.error('Error updating word status:', error);
    showToast('Network error when updating status', 'danger');
  }
}

/**
 * Show a toast notification
 * Creates a custom toast notification without Bootstrap dependency
 * @param {string} message - Message to display
 * @param {string} type - Color type (success, danger, warning, info)
 */
function showToast(message, type = 'info') {
  // Check for existing toast container
  let toastContainer = document.querySelector('.toast-container');

  // Create container if it doesn't exist
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }

  // Create a unique ID for this toast
  const toastId = 'toast-' + Date.now();

  // Create toast element
  const toast = document.createElement('div');
  toast.className = `toast bg-${type}`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('id', toastId);

  const dismissBtn = document.createElement('button');
  dismissBtn.className = 'btn-close';
  dismissBtn.setAttribute('aria-label', 'Close');
  dismissBtn.innerHTML = '&times;';

  const toastBody = document.createElement('div');
  toastBody.className = 'toast-body';
  toastBody.textContent = message;

  const flexContainer = document.createElement('div');
  flexContainer.className = 'd-flex';
  flexContainer.style.display = 'flex';
  flexContainer.style.justifyContent = 'space-between';
  flexContainer.style.alignItems = 'center';

  flexContainer.appendChild(toastBody);
  flexContainer.appendChild(dismissBtn);

  toast.appendChild(flexContainer);

  // Add to container
  toastContainer.appendChild(toast);

  // Add event listener for close button
  dismissBtn.addEventListener('click', function() {
    removeToast(toast);
  });

  // Auto-hide after delay
  setTimeout(() => {
    removeToast(toast);
  }, 3000);
}

/**
 * Remove a toast with animation
 * @param {HTMLElement} toast - The toast element to remove
 */
function removeToast(toast) {
  toast.style.opacity = '0';
  toast.style.transform = 'translateX(100%)';
  toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';

  setTimeout(() => {
    toast.remove();
  }, 300);
}