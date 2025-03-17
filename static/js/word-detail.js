/**
 * Word Detail Page JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
  initPronunciationPlayer();
  initStatusChanges();
  initExampleDisplay();
});

/**
 * Initialize pronunciation player functionality
 */
function initPronunciationPlayer() {
  const playButton = document.querySelector('.play-pronunciation');
  const audioElement = document.getElementById('pronunciationAudio');

  if (!playButton || !audioElement) return;

  // Play button click handler
  playButton.addEventListener('click', function() {
    if (audioElement.paused) {
      // If audio is paused, play it
      audioElement.play()
        .then(() => {
          playButton.innerHTML = '<i class="bi bi-pause"></i>';
          playButton.setAttribute('title', 'Pause pronunciation');
        })
        .catch(error => {
          console.error('Error playing audio:', error);
          showToast('Error playing pronunciation', 'danger');
        });
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