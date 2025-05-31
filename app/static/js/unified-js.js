/**
 * Unified JavaScript functions for all lesson components
 */

document.addEventListener('DOMContentLoaded', function() {
  // Initialize common UI elements
  initializeProgressBars();
  initializeCompletionButtons();
  initializeTooltips();
  initializeConfetti();

  // Check if lesson is completed and show celebration if needed
  const isCompleted = document.body.classList.contains('lesson-completed');
  if (isCompleted) {
    showCompletionCelebration();
  }
});

/**
 * Initialize all progress bars in the lesson
 */
function initializeProgressBars() {
  const progressElements = document.querySelectorAll('.lesson-progress');

  progressElements.forEach(progressEl => {
    const progressBar = progressEl.querySelector('.progress-bar');
    const progressText = progressEl.querySelector('.progress-text');

    // If this is a question-based progress, count answered questions
    if (progressEl.hasAttribute('data-question-progress')) {
      updateQuestionProgress();
    }

    // Attach event listeners for radio buttons and other inputs if needed
    const radioButtons = document.querySelectorAll('input[type="radio"]');
    radioButtons.forEach(radio => {
      radio.addEventListener('change', updateQuestionProgress);
    });

    function updateQuestionProgress() {
      const answeredQuestions = document.querySelectorAll('input[type="radio"]:checked').length;
      const totalQuestions = parseInt(progressEl.getAttribute('data-total-questions') || '0');

      if (totalQuestions > 0) {
        const progressPercent = (answeredQuestions / totalQuestions) * 100;
        progressBar.style.width = progressPercent + '%';
        progressBar.setAttribute('aria-valuenow', progressPercent);

        if (progressText) {
          progressText.textContent = answeredQuestions + '/' + totalQuestions;
        }

        // Enable submit button if all questions are answered
        const submitButton = document.querySelector('#submit-button');
        if (submitButton) {
          submitButton.disabled = answeredQuestions < totalQuestions;
        }
      }
    }
  });
}

/**
 * Initialize all completion buttons
 */
function initializeCompletionButtons() {
  const completeButtons = document.querySelectorAll('.btn-complete');

  completeButtons.forEach(button => {
    button.addEventListener('click', function(e) {
      // For buttons that require all exercises to be completed
      if (button.hasAttribute('data-requires-completion')) {
        const totalRequired = parseInt(button.getAttribute('data-requires-completion') || '0');
        const completedCount = document.querySelectorAll('.exercise-completed').length;

        if (completedCount < totalRequired) {
          e.preventDefault();
          alert('Please complete all exercises before proceeding.');
          return false;
        }
      }

      // If button triggers a completion modal
      if (button.hasAttribute('data-show-modal')) {
        e.preventDefault();
        const modalId = button.getAttribute('data-show-modal');
        const modal = document.getElementById(modalId);

        if (modal) {
          // Using Bootstrap modal if available
          if (typeof bootstrap !== 'undefined') {
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
          } else {
            modal.style.display = 'block';
          }

          // Show confetti
          showConfetti();
        }

        // If there's an AJAX call to mark completion
        if (button.hasAttribute('data-completion-url')) {
          const url = button.getAttribute('data-completion-url');
          fetchCompletion(url);
        }
      }
    });
  });
}

/**
 * Fetch completion status via AJAX
 */
function fetchCompletion(url) {
  fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: JSON.stringify({})
  })
  .then(response => {
    if (!response.ok) {
      throw new Error('Network response was not ok');
    }
    return response.json();
  })
  .then(data => {
    if (data.success) {
      document.body.classList.add('lesson-completed');

      // Enable navigation to next lesson
      const nextButton = document.querySelector('.btn-next.disabled');
      if (nextButton) {
        nextButton.classList.remove('disabled');
        nextButton.setAttribute('aria-disabled', 'false');
      }
    }
  })
  .catch(error => {
    console.error('Error:', error);
    alert('There was an error completing the lesson. Please try again.');
  });
}

/**
 * Initialize tooltips for vocabulary words
 */
function initializeTooltips() {
  const tooltipTriggers = document.querySelectorAll('.word-highlight');
  const tooltipElement = document.getElementById('word-tooltip');

  if (!tooltipElement) return;

  tooltipTriggers.forEach(trigger => {
    trigger.addEventListener('click', function(e) {
      const word = this.getAttribute('data-word');
      const translation = this.getAttribute('data-translation');

      const wordElement = tooltipElement.querySelector('.word-tooltip-word');
      const translationElement = tooltipElement.querySelector('.word-tooltip-translation');

      if (wordElement) wordElement.textContent = word;
      if (translationElement) translationElement.textContent = translation;

      // Position the tooltip
      const rect = this.getBoundingClientRect();
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

      tooltipElement.style.left = rect.left + 'px';
      tooltipElement.style.top = (rect.bottom + scrollTop + 10) + 'px';
      tooltipElement.style.display = 'block';
    });
  });

  // Hide tooltip when clicking elsewhere
  document.addEventListener('click', function(e) {
    if (!e.target.classList.contains('word-highlight')) {
      tooltipElement.style.display = 'none';
    }
  });
}

/**
 * Show completion celebration with confetti
 */
function showCompletionCelebration() {
  // Show celebration section
  const celebrationElement = document.querySelector('.completion-celebration');
  if (celebrationElement) {
    celebrationElement.style.display = 'block';

    // Scroll to celebration
    setTimeout(() => {
      celebrationElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 500);
  }

  // Show confetti
  showConfetti();
}

/**
 * Initialize confetti canvas and animation
 */
function initializeConfetti() {
  // Create canvas if it doesn't exist
  let canvas = document.getElementById('confetti-canvas');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'confetti-canvas';
    canvas.style.position = 'fixed';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.pointerEvents = 'none';
    canvas.style.zIndex = '100';
    canvas.style.display = 'none';
    document.body.appendChild(canvas);
  }
}

/**
 * Show confetti animation
 */
function showConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  if (!canvas) return;

  canvas.style.display = 'block';
  const width = window.innerWidth;
  const height = window.innerHeight;
  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext('2d');
  const confetti = [];
  const confettiCount = 300;
  const gravity = 0.5;
  const terminalVelocity = 5;
  const drag = 0.075;
  const colors = [
    {front: 'rgba(0,195,255,1)', back: 'rgba(0,115,190,1)'},
    {front: 'rgba(255,87,51,1)', back: 'rgba(190,45,15,1)'},
    {front: 'rgba(255,230,0,1)', back: 'rgba(230,190,0,1)'},
    {front: 'rgba(0,230,118,1)', back: 'rgba(0,190,100,1)'},
    {front: 'rgba(179,0,255,1)', back: 'rgba(140,0,200,1)'}
  ];

  // Initialize confetti particles
  for (let i = 0; i < confettiCount; i++) {
    confetti.push({
      color: colors[Math.floor(Math.random() * colors.length)],
      dimensions: {
        x: Math.random() * 15 + 10,
        y: Math.random() * 15 + 10
      },
      position: {
        x: Math.random() * width,
        y: Math.random() * height - height
      },
      rotation: Math.random() * 2 * Math.PI,
      scale: {x: 1, y: 1},
      velocity: {
        x: Math.random() * 6 - 3,
        y: Math.random() * 3 + 3
      }
    });
  }

  // Animation loop
  let animationFrame;
  const render = () => {
    ctx.clearRect(0, 0, width, height);

    confetti.forEach((confetto, index) => {
      let width = confetto.dimensions.x * confetto.scale.x;
      let height = confetto.dimensions.y * confetto.scale.y;

      // Update position
      confetto.velocity.x -= confetto.velocity.x * drag;
      confetto.velocity.y = Math.min(confetto.velocity.y + gravity, terminalVelocity);
      confetto.velocity.x += Math.random() > 0.5 ? Math.random() : -Math.random();

      confetto.position.x += confetto.velocity.x;
      confetto.position.y += confetto.velocity.y;

      // Rotate confetto
      confetto.rotation += 0.01;

      // Draw confetto
      ctx.save();
      ctx.translate(confetto.position.x, confetto.position.y);
      ctx.rotate(confetto.rotation);

      const colorIndex = Math.floor(Math.abs(Math.cos(confetto.rotation)) * 2);
      ctx.fillStyle = colorIndex === 0 ? confetto.color.front : confetto.color.back;

      ctx.fillRect(-width / 2, -height / 2, width, height);
      ctx.restore();

      // Remove confetti that fall below the screen
      if (confetto.position.y >= height) confetti.splice(index, 1);
    });

    // Continue animation if there are still particles
    if (confetti.length > 0) {
      animationFrame = requestAnimationFrame(render);
    } else {
      canvas.style.display = 'none';
    }
  };

  render();

  // Stop animation after 7 seconds
  setTimeout(() => {
    cancelAnimationFrame(animationFrame);
    canvas.style.display = 'none';
  }, 7000);
}

/**
 * Initialize Anki-style flashcards
 */
function initializeAnkiCards() {
  const cards = document.querySelectorAll('.anki-card');
  const prevButton = document.getElementById('prev-card');
  const nextButton = document.getElementById('next-card');
  const currentCardEl = document.getElementById('current-card');
  const totalCardsEl = document.getElementById('total-cards');

  if (!cards.length) return;

  let currentCardIndex = 0;
  const totalCards = cards.length;

  // Initialize counter
  if (totalCardsEl) totalCardsEl.textContent = totalCards;

  // Card click handler - flip card
  cards.forEach(card => {
    card.addEventListener('click', function() {
      this.classList.toggle('flipped');
    });
  });

  // Navigation handlers
  if (prevButton) {
    prevButton.addEventListener('click', function() {
      if (currentCardIndex > 0) {
        // Hide current card
        cards[currentCardIndex].classList.add('d-none');
        cards[currentCardIndex].classList.remove('flipped');

        // Show previous card
        currentCardIndex--;
        cards[currentCardIndex].classList.remove('d-none');

        // Update counter
        if (currentCardEl) currentCardEl.textContent = currentCardIndex + 1;

        // Update button states
        updateButtonStates();
      }
    });
  }

  if (nextButton) {
    nextButton.addEventListener('click', function() {
      if (currentCardIndex < totalCards - 1) {
        // Hide current card
        cards[currentCardIndex].classList.add('d-none');
        cards[currentCardIndex].classList.remove('flipped');

        // Show next card
        currentCardIndex++;
        cards[currentCardIndex].classList.remove('d-none');

        // Update counter
        if (currentCardEl) currentCardEl.textContent = currentCardIndex + 1;

        // Update button states
        updateButtonStates();
      }
    });
  }

  function updateButtonStates() {
    if (prevButton) prevButton.disabled = currentCardIndex === 0;
    if (nextButton) nextButton.disabled = currentCardIndex === totalCards - 1;
  }

  // Initialize button states
  updateButtonStates();

  // Optional: Keyboard navigation
  document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowLeft' && prevButton) {
      prevButton.click();
    } else if (e.key === 'ArrowRight' && nextButton) {
      nextButton.click();
    } else if (e.key === ' ' || e.key === 'Spacebar') {
      // Flip current card with spacebar
      cards[currentCardIndex].click();
    }
  });
}

// Initialize Anki cards if present on the page
if (document.querySelector('.anki-container')) {
  initializeAnkiCards();
}