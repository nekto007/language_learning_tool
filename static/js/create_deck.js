/**
 * Create Deck Page JavaScript
 * Handles form validation and submission feedback
 */

document.addEventListener('DOMContentLoaded', () => {
  // Initialize the create deck form
  initCreateDeckForm();

  // Add animation to cards
  animateCards();
});

/**
 * Initialize form validation and submission handling
 */
function initCreateDeckForm() {
  const form = document.getElementById('createDeckForm');
  const nameInput = document.getElementById('name');
  const descriptionInput = document.getElementById('description');
  const submitButton = document.getElementById('createDeckBtn');

  if (!form || !nameInput || !submitButton) return;

  // Focus name input on page load
  nameInput.focus();

  // Set up form submission
  form.addEventListener('submit', (event) => {
    // Prevent default submission to validate
    if (!validateForm()) {
      event.preventDefault();
      return false;
    }

    // Show loading state on button
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Creating...';
  });

  // Set up auto-resize for textarea
  if (descriptionInput) {
    descriptionInput.addEventListener('input', autoResizeTextarea);
    // Initial resize
    autoResizeTextarea.call(descriptionInput);
  }

  /**
   * Validate the form before submission
   * @returns {boolean} Whether the form is valid
   */
  function validateForm() {
    let isValid = true;

    // Validate name (required & max length)
    if (!nameInput.value.trim()) {
      showError(nameInput, 'Please enter a deck name');
      isValid = false;
    } else if (nameInput.value.length > 50) {
      showError(nameInput, 'Deck name must be 50 characters or less');
      isValid = false;
    } else {
      clearError(nameInput);
    }

    // Validate description (max length only)
    if (descriptionInput && descriptionInput.value.length > 500) {
      showError(descriptionInput, 'Description must be 500 characters or less');
      isValid = false;
    } else if (descriptionInput) {
      clearError(descriptionInput);
    }

    return isValid;
  }

  /**
   * Show error message for an input
   * @param {HTMLElement} input - The input element
   * @param {string} message - Error message to display
   */
  function showError(input, message) {
    // Clear existing error first
    clearError(input);

    // Create error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'invalid-feedback';
    errorDiv.textContent = message;

    // Add error styling
    input.classList.add('is-invalid');

    // Insert error after input
    input.parentNode.insertBefore(errorDiv, input.nextSibling);
  }

  /**
   * Clear error message for an input
   * @param {HTMLElement} input - The input element
   */
  function clearError(input) {
    input.classList.remove('is-invalid');
    const errorElement = input.parentNode.querySelector('.invalid-feedback');
    if (errorElement) {
      errorElement.remove();
    }
  }
}

/**
 * Auto-resize textarea to fit content
 */
function autoResizeTextarea() {
  this.style.height = 'auto';
  this.style.height = (this.scrollHeight) + 'px';
}

/**
 * Add entrance animations to cards
 */
function animateCards() {
  const elements = [
    document.querySelector('.deck-form-card'),
    document.querySelector('.deck-tips-card')
  ].filter(elem => elem !== null);

  elements.forEach((element, index) => {
    // Set initial invisible state
    element.style.opacity = '0';
    element.style.transform = 'translateY(20px)';

    // Trigger animation with staggered delay
    setTimeout(() => {
      element.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      element.style.opacity = '1';
      element.style.transform = 'translateY(0)';
    }, 100 + (index * 100));
  });
}