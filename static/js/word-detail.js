/**
 * Word Detail Page JavaScript
 * Enhanced for mobile compatibility
 */

document.addEventListener('DOMContentLoaded', function() {
  // Detect if we're on a mobile device
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

  if (isMobile) {
    // Initialize the mobile-optimized player
    initMobileAudioPlayer();
  } else {
    // Desktop player initialization
    initPronunciationPlayer();
  }

  initStatusChanges();
  initExampleDisplay();
});

/**
 * Initialize mobile-optimized audio player
 */
function initMobileAudioPlayer() {
  // Get audio element and check if it exists
  const audioElement = document.getElementById('pronunciationAudio');
  if (!audioElement) return;

  // Get container for the player
  const container = document.querySelector('.pronunciation-player');
  if (!container) return;

  // Get source URL
  const audioSource = audioElement.querySelector('source');
  if (!audioSource || !audioSource.src) {
    console.error('Audio source not found');
    showErrorMessage(container);
    return;
  }

  // Create custom mobile player
  const customPlayer = document.createElement('div');
  customPlayer.className = 'mobile-audio-player';
  customPlayer.innerHTML = `
    <button class="mobile-play-button" id="mobilePlayButton">
      <i class="bi bi-play-fill"></i>
    </button>
    <div class="mobile-audio-progress" id="mobileProgress">
      <div class="mobile-audio-progress-bar" id="mobileProgressBar"></div>
    </div>
    <span class="mobile-audio-time" id="mobileAudioTime">0:00</span>
  `;

  // Remove existing play button and audio element
  const existingButton = container.querySelector('.play-pronunciation');
  if (existingButton) {
    existingButton.remove();
  }

  // Add new player to container
  container.appendChild(customPlayer);

  // Create a new audio object
  const audio = new Audio(audioSource.src);
  let isLoading = true;

  // Show loading state
  showLoadingState(customPlayer);

  // Set up event listeners for mobile audio
  const playButton = document.getElementById('mobilePlayButton');
  const progressBar = document.getElementById('mobileProgressBar');
  const progressContainer = document.getElementById('mobileProgress');
  const timeDisplay = document.getElementById('mobileAudioTime');

  // Handle audio loading
  audio.addEventListener('canplaythrough', function() {
    isLoading = false;
    hideLoadingState(customPlayer);
    playButton.innerHTML = '<i class="bi bi-play-fill"></i>';
    playButton.disabled = false;
  });

  // Handle play button click
  playButton.addEventListener('click', function() {
    if (isLoading) return;

    if (audio.paused) {
      // Force interaction to unlock audio in iOS Safari
      audio.load();

      // Play the audio with promise handling
      const playPromise = audio.play();

      if (playPromise !== undefined) {
        playPromise.then(_ => {
          // Playback started successfully
          playButton.innerHTML = '<i class="bi bi-pause-fill"></i>';
        })
        .catch(error => {
          // Auto-play was prevented
          console.error("Audio playback failed:", error);

          // Create a visual feedback for the user
          const container = document.createElement('div');
          container.style.position = 'fixed';
          container.style.top = '50%';
          container.style.left = '50%';
          container.style.transform = 'translate(-50%, -50%)';
          container.style.backgroundColor = 'rgba(0,0,0,0.8)';
          container.style.color = 'white';
          container.style.padding = '20px';
          container.style.borderRadius = '10px';
          container.style.zIndex = '9999';
          container.innerHTML = `
            <div style="text-align:center">
              <i class="bi bi-volume-up" style="font-size: 2rem; margin-bottom: 10px;"></i>
              <p>Tap to play audio</p>
            </div>
          `;
          document.body.appendChild(container);

          // Remove the message when clicked
          container.addEventListener('click', function() {
            audio.play().then(() => {
              playButton.innerHTML = '<i class="bi bi-pause-fill"></i>';
              document.body.removeChild(container);
            }).catch(e => {
              console.error("Still could not play audio:", e);
            });
          });
        });
      }
    } else {
      audio.pause();
      playButton.innerHTML = '<i class="bi bi-play-fill"></i>';
    }
  });

  // Handle progress updates
  audio.addEventListener('timeupdate', function() {
    if (isLoading) return;

    const percentage = (audio.currentTime / audio.duration) * 100;
    progressBar.style.width = percentage + '%';

    // Update time display
    const currentMinutes = Math.floor(audio.currentTime / 60);
    const currentSeconds = Math.floor(audio.currentTime % 60);
    timeDisplay.textContent = `${currentMinutes}:${currentSeconds < 10 ? '0' : ''}${currentSeconds}`;
  });

  // Handle progress bar clicks
  progressContainer.addEventListener('click', function(e) {
    if (isLoading || !audio.duration) return;

    const rect = progressContainer.getBoundingClientRect();
    const position = (e.clientX - rect.left) / rect.width;
    audio.currentTime = position * audio.duration;
  });

  // Handle audio ended
  audio.addEventListener('ended', function() {
    playButton.innerHTML = '<i class="bi bi-play-fill"></i>';
    progressBar.style.width = '0%';
    audio.currentTime = 0;
  });

  // Handle audio errors
  audio.addEventListener('error', function(e) {
    console.error('Audio error:', e);
    showErrorMessage(customPlayer);
  });

  // Handle stalled/waiting audio
  audio.addEventListener('waiting', function() {
    isLoading = true;
    showLoadingState(customPlayer);
  });
}

/**
 * Show loading state in the audio player
 */
function showLoadingState(container) {
  // Hide play button
  const playButton = container.querySelector('#mobilePlayButton');
  if (playButton) {
    playButton.innerHTML = '<div class="spinner"></div>';
    playButton.disabled = true;
  }
}

/**
 * Hide loading state in the audio player
 */
function hideLoadingState(container) {
  // Show play button
  const playButton = container.querySelector('#mobilePlayButton');
  if (playButton) {
    playButton.innerHTML = '<i class="bi bi-play-fill"></i>';
    playButton.disabled = false;
  }
}

/**
 * Show error message when audio fails
 */
function showErrorMessage(container) {
  // Create error message
  const errorMsg = document.createElement('div');
  errorMsg.className = 'audio-error';
  errorMsg.innerHTML = `
    <div style="display: flex; align-items: center; color: #ff6b6b;">
      <i class="bi bi-exclamation-triangle me-2"></i>
      <span>Unable to load audio</span>
    </div>
  `;

  // Clear container and append error
  container.innerHTML = '';
  container.appendChild(errorMsg);
}

/**
 * Initialize pronunciation player functionality (desktop version)
 */
function initPronunciationPlayer() {
  const playButton = document.querySelector('.play-pronunciation');
  const audioElement = document.getElementById('pronunciationAudio');

  if (!playButton || !audioElement) return;

  // Play button click handler
  playButton.addEventListener('click', function() {
    // Force reload audio to bypass iOS restrictions
    audioElement.load();

    if (audioElement.paused) {
      // If audio is paused, play it
      const playPromise = audioElement.play();

      if (playPromise !== undefined) {
        playPromise.then(() => {
          playButton.innerHTML = '<i class="bi bi-pause"></i>';
          playButton.setAttribute('title', 'Pause pronunciation');
        })
        .catch(error => {
          console.error('Error playing audio:', error);
          showToast('Error playing pronunciation. Tap the button again.', 'warning');
        });
      }
    } else {
      // If audio is playing, pause it
      audioElement.pause();
      playButton.innerHTML = '<i class="bi bi-volume-up"></i>';
      playButton.setAttribute('title', 'Play pronunciation');
    }
  });

  // Audio ended event handler
  audioElement.addEventListener('ended', function() {
    playButton.innerHTML = '<i class="bi bi-volume-up"></i>';
    playButton.setAttribute('title', 'Play pronunciation');
  });

  // Audio error handler
  audioElement.addEventListener('error', function() {
    showToast('Error loading pronunciation audio', 'danger');
    playButton.disabled = true;
    playButton.classList.add('btn-secondary');
    playButton.classList.remove('btn-primary');
    playButton.innerHTML = '<i class="bi bi-volume-mute"></i>';
  });
}

/**
 * Initialize word status changes
 */
function initStatusChanges() {
  const statusButtons = document.querySelectorAll('.status-item');

  statusButtons.forEach(button => {
    button.addEventListener('click', function() {
      // Extract word ID and status ID from the onclick attribute
      const onclickAttr = this.getAttribute('onclick');
      const match = onclickAttr.match(/updateWordStatus\((\d+),\s*(\d+)\)/);

      if (match && match.length === 3) {
        const wordId = parseInt(match[1]);
        const statusId = parseInt(match[2]);

        // Call the update function
        updateWordStatus(wordId, statusId);
      }
    });
  });
}

/**
 * Update word status via API
 * @param {number} wordId - Word ID
 * @param {number} statusId - New status ID
 */
function updateWordStatus(wordId, statusId) {
  // Get current status button for visual feedback
  const currentStatusButton = document.querySelector(`.status-item[onclick*="updateWordStatus(${wordId}, ${statusId})"]`);

  if (currentStatusButton && currentStatusButton.classList.contains('active')) {
    // Status is already set to this value
    return;
  }

  // Show loading state
  const statusButtons = document.querySelectorAll('.status-item');
  statusButtons.forEach(button => {
    button.disabled = true;
    button.style.opacity = '0.7';
  });

  // Make API call to update status
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
      showToast('Word status updated successfully', 'success');

      // Update UI without page reload
      updateStatusUI(statusId);
    } else {
      showToast(`Failed to update status: ${data.error}`, 'danger');

      // Re-enable buttons
      statusButtons.forEach(button => {
        button.disabled = false;
        button.style.opacity = '1';
      });
    }
  },
  // Error callback
  function(error) {
    showToast(`Error updating status: ${error.message}`, 'danger');

    // Re-enable buttons
    statusButtons.forEach(button => {
      button.disabled = false;
      button.style.opacity = '1';
    });
  });
}

/**
 * Update status UI elements
 * @param {number} newStatusId - New status ID
 */
function updateStatusUI(newStatusId) {
  // Update status badge
  const statusBadge = document.querySelector('.status-badge');
  if (statusBadge) {
    // Remove old status class
    for (let i = 0; i < 5; i++) {
      statusBadge.classList.remove(`status-${i}`);
    }
    // Add new status class
    statusBadge.classList.add(`status-${newStatusId}`);
    // Update text
    const statusLabels = {
      0: 'New',
      1: 'Available',
      2: 'Queued',
      3: 'Active',
      4: 'Learned'
    };
    statusBadge.textContent = statusLabels[newStatusId] || 'Unknown';
  }

  // Update status list UI
  const statusItems = document.querySelectorAll('.status-item');
  statusItems.forEach(item => {
    // Remove active class and current badge from all
    item.classList.remove('active');
    const currentBadge = item.querySelector('.current-badge');
    if (currentBadge) {
      currentBadge.remove();
    }

    // Re-enable all buttons
    item.disabled = false;
    item.style.opacity = '1';

    // Check if this is the new active status
    const onclickAttr = item.getAttribute('onclick');
    if (onclickAttr && onclickAttr.includes(`updateWordStatus(${document.location.pathname.split('/').pop()}, ${newStatusId})`)) {
      // This is the new active status
      item.classList.add('active');

      // Add "Current" badge
      const statusContent = item.querySelector('.status-content');
      if (statusContent) {
        const badge = document.createElement('span');
        badge.className = 'current-badge';
        badge.textContent = 'Current';
        statusContent.appendChild(badge);
      }
    }
  });

  // Add transition effect
  document.querySelector('.word-header').style.backgroundColor = 'rgba(var(--primary-color-rgb), 0.05)';
  setTimeout(() => {
    document.querySelector('.word-header').style.backgroundColor = '';
  }, 1000);
}

/**
 * Initialize example sentences display
 */
function initExampleDisplay() {
  const exampleSection = document.querySelector('.example-sentences');
  if (!exampleSection) return;

  // Format the example sentences for better display
  const exampleParagraphs = exampleSection.querySelectorAll('p');
  exampleParagraphs.forEach(paragraph => {
    // Highlight the word in examples
    const wordToHighlight = document.querySelector('.word-title').textContent.trim().toLowerCase();

    // Skip paragraphs that are likely translations (shorter, different language)
    // This is a simple heuristic and might need adjustment

    // Create a temporary div to parse HTML content properly
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = paragraph.innerHTML;
    const textContent = tempDiv.textContent;

    // Only highlight in paragraphs that are likely English examples
    if (textContent.toLowerCase().includes(wordToHighlight)) {
      // Create a highlight using case-insensitive regex
      const regex = new RegExp(`(\\b${wordToHighlight}\\b)`, 'gi');
      paragraph.innerHTML = paragraph.innerHTML.replace(
        regex,
        '<span class="word-highlight">$1</span>'
      );
    }
  });

  // Add CSS for the highlight
  const style = document.createElement('style');
  style.textContent = `
    .word-highlight {
      background-color: rgba(var(--primary-color-rgb), 0.2);
      border-radius: 2px;
      padding: 0 2px;
    }
  `;
  document.head.appendChild(style);
}

/**
 * Helper function to show toast notifications
 * @param {string} message - The message to display
 * @param {string} type - Type of toast (success, danger, warning)
 */
function showToast(message, type = 'success') {
  // Create toast container if it doesn't exist
  let toastContainer = document.querySelector('.toast-container');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }

  // Create toast element
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  // Set icon based on type
  let icon = 'check-circle';
  if (type === 'danger') icon = 'exclamation-circle';
  if (type === 'warning') icon = 'exclamation-triangle';

  toast.innerHTML = `
    <i class="bi bi-${icon} toast-icon"></i>
    <span>${message}</span>
  `;

  // Add to container
  toastContainer.appendChild(toast);

  // Remove after delay
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-20px)';
    toast.style.transition = 'opacity 0.3s, transform 0.3s';

    setTimeout(() => {
      if (toast.parentNode === toastContainer) {
        toastContainer.removeChild(toast);
      }

      // Remove container if empty
      if (toastContainer.children.length === 0) {
        document.body.removeChild(toastContainer);
      }
    }, 300);
  }, 3000);
}

/**
 * Helper function to make API calls
 * @param {string} url - API endpoint
 * @param {object} options - Fetch options
 * @param {function} onSuccess - Success callback
 * @param {function} onError - Error callback
 */
function callApi(url, options, onSuccess, onError) {
  // Default headers
  const headers = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest'
  };

  // Add CSRF token if available
  const csrfToken = document.querySelector('meta[name="csrf-token"]');
  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken.getAttribute('content');
  }

  // Merge options
  const fetchOptions = {
    ...options,
    headers: {
      ...headers,
      ...(options.headers || {})
    }
  };

  // Make the fetch call
  fetch(url, fetchOptions)
    .then(response => {
      if (!response.ok) {
        throw new Error(`Network response was not ok: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      if (onSuccess) onSuccess(data);
    })
    .catch(error => {
      console.error('API call failed:', error);
      if (onError) onError(error);
    });
}