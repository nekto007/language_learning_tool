/**
 * Authentication Pages JavaScript
 * For login and registration pages
 */

document.addEventListener('DOMContentLoaded', function() {
  initPasswordToggle();
  initFormValidation();
  initPasswordStrength();
});

/**
 * Initialize password visibility toggle
 */
function initPasswordToggle() {
  const toggleButtons = document.querySelectorAll('.toggle-password');

  toggleButtons.forEach(button => {
    button.addEventListener('click', function() {
      const targetId = this.getAttribute('data-target');
      const passwordInput = document.getElementById(targetId);

      // Toggle password visibility
      if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        this.innerHTML = '<i class="bi bi-eye-slash"></i>';
        this.setAttribute('title', 'Hide Password');
      } else {
        passwordInput.type = 'password';
        this.innerHTML = '<i class="bi bi-eye"></i>';
        this.setAttribute('title', 'Show Password');
      }
    });
  });
}

/**
 * Initialize form validation
 */
function initFormValidation() {
  // Fetch all forms with the 'needs-validation' class
  const forms = document.querySelectorAll('.needs-validation');

  // Loop over them and prevent submission
  Array.from(forms).forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }

      form.classList.add('was-validated');

      // Custom validation for the agreement checkbox
      const agreeCheckbox = form.querySelector('#agree');
      if (agreeCheckbox && !agreeCheckbox.checked) {
        agreeCheckbox.setCustomValidity('You must agree to the terms and conditions');
      } else if (agreeCheckbox) {
        agreeCheckbox.setCustomValidity('');
      }
    }, false);

    // Clear custom validity when checkbox is clicked
    const agreeCheckbox = form.querySelector('#agree');
    if (agreeCheckbox) {
      agreeCheckbox.addEventListener('click', function() {
        if (this.checked) {
          this.setCustomValidity('');
        } else {
          this.setCustomValidity('You must agree to the terms and conditions');
        }
      });
    }
  });
}

/**
 * Initialize password strength meter
 */
function initPasswordStrength() {
  const passwordInput = document.getElementById('password');
  const progressBar = document.querySelector('.password-strength .progress-bar');
  const feedbackElement = document.querySelector('.password-feedback');

  if (!passwordInput || !progressBar || !feedbackElement) return;

  passwordInput.addEventListener('input', function() {
    const password = this.value;
    const strength = calculatePasswordStrength(password);

    // Update progress bar
    progressBar.style.width = `${strength.score * 25}%`;
    progressBar.className = 'progress-bar';

    if (strength.score > 0) {
      progressBar.classList.add(strength.class);
    }

    // Update feedback text
    feedbackElement.textContent = `Password strength: ${strength.feedback}`;
  });
}

/**
 * Calculate password strength
 * @param {string} password - Password to check
 * @returns {Object} - Strength score, feedback and class
 */
function calculatePasswordStrength(password) {
  // No password
  if (!password) {
    return {
      score: 0,
      feedback: 'Too weak',
      class: 'weak'
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

  // Determine strength class and feedback
  let feedback, strengthClass;

  if (score < 2) {
    feedback = 'Too weak';
    strengthClass = 'weak';
  } else if (score < 3) {
    feedback = 'Could be stronger';
    strengthClass = 'medium';
  } else if (score < 4) {
    feedback = 'Good';
    strengthClass = 'medium';
  } else {
    feedback = 'Strong';
    strengthClass = 'strong';
  }

  return {
    score: Math.min(4, score),
    feedback: feedback,
    class: strengthClass
  };
}