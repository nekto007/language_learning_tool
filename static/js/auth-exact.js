/**
 * Authentication Pages JavaScript
 * Exact design match version
 */

document.addEventListener('DOMContentLoaded', function() {
  initPasswordToggle();
  initPasswordStrength();
  initFormValidation();
});

/**
 * Initialize password visibility toggle
 */
function initPasswordToggle() {
  const toggleButtons = document.querySelectorAll('.toggle-password');

  toggleButtons.forEach(button => {
    button.addEventListener('click', function() {
      const passwordInput = this.parentNode.querySelector('input');

      // Toggle password visibility
      if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        this.innerHTML = '<i class="bi bi-eye-slash"></i>';
      } else {
        passwordInput.type = 'password';
        this.innerHTML = '<i class="bi bi-eye"></i>';
      }
    });
  });
}

/**
 * Initialize password strength meter
 */
function initPasswordStrength() {
  const passwordInput = document.getElementById('password');
  const strengthIndicator = document.getElementById('passwordStrength');

  if (!passwordInput || !strengthIndicator) return;

  passwordInput.addEventListener('input', function() {
    const password = this.value;
    const strength = calculatePasswordStrength(password);

    // Update strength text
    strengthIndicator.textContent = `Password strength: ${strength.feedback}`;
  });
}

/**
 * Calculate password strength
 * @param {string} password - Password to check
 * @returns {Object} - Strength score and feedback
 */
function calculatePasswordStrength(password) {
  // No password
  if (!password) {
    return {
      score: 0,
      feedback: 'Too weak'
    };
  }

  let score = 0;

  // Add points for length
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;

  // Add points for complexity
  if (/[A-Z]/.test(password)) score += 0.5;
  if (/[a-z]/.test(password)) score += 0.5;
  if (/[0-9]/.test(password)) score += 0.5;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;

  // Determine feedback
  let feedback;

  if (score < 2) {
    feedback = 'Too weak';
  } else if (score < 3) {
    feedback = 'Could be stronger';
  } else if (score < 4) {
    feedback = 'Good';
  } else {
    feedback = 'Strong';
  }

  return {
    score: Math.min(4, score),
    feedback: feedback
  };
}

/**
 * Initialize form validation
 */
function initFormValidation() {
  const forms = document.querySelectorAll('form');

  forms.forEach(form => {
    form.addEventListener('submit', function(event) {
      let isValid = true;

      // Basic input validation
      const requiredInputs = form.querySelectorAll('input[required]');
      requiredInputs.forEach(input => {
        if (!input.value.trim()) {
          isValid = false;
          highlightInvalidInput(input);
        } else {
          removeInvalidHighlight(input);
        }
      });

      // Email validation if present
      const emailInput = form.querySelector('input[type="email"]');
      if (emailInput && emailInput.value.trim() && !isValidEmail(emailInput.value)) {
        isValid = false;
        highlightInvalidInput(emailInput);
      }

      // Prevent form submission if invalid
      if (!isValid) {
        event.preventDefault();
      }
    });
  });

  // Add input event listeners to clear invalid state
  document.querySelectorAll('input').forEach(input => {
    input.addEventListener('input', function() {
      removeInvalidHighlight(this);
    });
  });
}

/**
 * Highlight invalid input
 * @param {HTMLElement} input - Input element to highlight
 */
function highlightInvalidInput(input) {
  input.style.borderColor = 'red';
  input.style.boxShadow = '0 0 0 1px red';
}

/**
 * Remove invalid input highlight
 * @param {HTMLElement} input - Input element to reset
 */
function removeInvalidHighlight(input) {
  input.style.borderColor = '';
  input.style.boxShadow = '';
}

/**
 * Validate email format
 * @param {string} email - Email to validate
 * @returns {boolean} - True if valid
 */
function isValidEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}