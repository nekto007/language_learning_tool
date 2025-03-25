/**
 * Word Detail Page JavaScript
 * Handles audio, theme toggle, status changes, and deck management
 */

// Initialize the page when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  initThemeToggle();
  initAudioPlayer();
  initStatusButtons();
  initDeckButtons();
});

/**
 * Initialize theme toggle functionality
 */
function initThemeToggle() {
  const themeToggle = document.getElementById('themeToggle');
  if (!themeToggle) return;

  // Check for saved theme preference or use system preference
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  // Set initial theme
  if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
  }

  // Toggle theme on button click
  themeToggle.addEventListener('click', function() {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    document.documentElement.setAttribute('data-bs-theme', newTheme);
    localStorage.setItem('theme', newTheme);
  });
}

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
      const modal = new bootstrap.Modal(document.getElementById('addToDeckModal'));
      modal.show();
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
      // Close modal and reload page
      const modal = bootstrap.Modal.getInstance(document.getElementById('addToDeckModal'));
      if (modal) {
        modal.hide();
      }

      showToast('Word successfully added to deck', 'success');

      // Reload page after a short delay to show the toast
      setTimeout(() => {
        window.location.reload();
      }, 1000);
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
      }, 1000);
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
      }, 1000);
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
 * Using Bootstrap 5 toast, creates temporary toast if needed
 * @param {string} message - Message to display
 * @param {string} type - Bootstrap color type (success, danger, warning, info)
 */
function showToast(message, type = 'info') {
  // Check for existing toast container
  let toastContainer = document.querySelector('.toast-container');

  // Create container if it doesn't exist
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(toastContainer);
  }

  // Create a unique ID for this toast
  const toastId = 'toast-' + Date.now();

  // Create toast element
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
  const bsToast = new bootstrap.Toast(toast, {
    delay: 3000,
    autohide: true
  });

  bsToast.show();

  // Remove from DOM after hiding
  toast.addEventListener('hidden.bs.toast', function() {
    toast.remove();
  });
}