/**
 * Common JavaScript functions for Language Learning Tool
 */

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
  initThemeToggle();
  initTooltips();
  initToasts();
  handleFlashMessages();
});

/**
 * Theme Toggling Functionality
 */
function initThemeToggle() {
  const toggleThemeBtn = document.getElementById('toggleThemeBtn');
  const htmlElement = document.documentElement;

  // Check for saved theme preference or use system preference
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  // Set initial theme
  if (savedTheme) {
    htmlElement.setAttribute('data-bs-theme', savedTheme);
    updateThemeIcon(savedTheme);
  } else if (prefersDark) {
    htmlElement.setAttribute('data-bs-theme', 'dark');
    updateThemeIcon('dark');
  }

  // Toggle theme on button click
  if (toggleThemeBtn) {
    toggleThemeBtn.addEventListener('click', function() {
      const currentTheme = htmlElement.getAttribute('data-bs-theme');
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

      htmlElement.setAttribute('data-bs-theme', newTheme);
      localStorage.setItem('theme', newTheme);
      updateThemeIcon(newTheme);

      // Show confirmation toast
      showToast(`Switched to ${newTheme} theme`, 'info');
    });
  }
}

/**
 * Update theme toggle button icon
 */
function updateThemeIcon(theme) {
  const toggleThemeBtn = document.getElementById('toggleThemeBtn');
  if (toggleThemeBtn) {
    const icon = toggleThemeBtn.querySelector('i') || document.createElement('i');
    icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon';

    if (!toggleThemeBtn.contains(icon)) {
      toggleThemeBtn.innerHTML = '';
      toggleThemeBtn.appendChild(icon);
    }
  }
}

/**
 * Initialize Bootstrap tooltips
 */
function initTooltips() {
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function(tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
}

/**
 * Initialize toast container
 */
function initToasts() {
  window.toastContainer = document.querySelector('.toast-container');
  if (!window.toastContainer) {
    window.toastContainer = document.createElement('div');
    window.toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(window.toastContainer);
  }
}

/**
 * Show a toast notification
 * @param {string} message - Message to display
 * @param {string} type - Bootstrap color type (success, danger, warning, info)
 * @param {number} delay - Time in ms before auto-hiding (default: 3000)
 */
function showToast(message, type = 'info', delay = 3000) {
  // Create toast element
  const toastId = 'toast-' + Date.now();
  const toastEl = document.createElement('div');
  toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
  toastEl.setAttribute('role', 'alert');
  toastEl.setAttribute('aria-live', 'assertive');
  toastEl.setAttribute('aria-atomic', 'true');
  toastEl.setAttribute('id', toastId);

  // Create toast content
  toastEl.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">
        ${message}
      </div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
    </div>
  `;

  // Add to container and initialize
  window.toastContainer.appendChild(toastEl);
  const toast = new bootstrap.Toast(toastEl, {
    delay: delay,
    autohide: true
  });

  // Show toast and remove from DOM after hiding
  toast.show();
  toastEl.addEventListener('hidden.bs.toast', function() {
    toastEl.remove();
  });

  return toast;
}

/**
 * Handle flash messages by converting them to toasts
 */
function handleFlashMessages() {
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    const message = alert.textContent.trim();
    const type = alert.classList.contains('alert-success') ? 'success' :
                alert.classList.contains('alert-danger') ? 'danger' :
                alert.classList.contains('alert-warning') ? 'warning' : 'info';

    showToast(message, type);
    alert.remove();
  });
}

/**
 * AJAX helper function for API calls
 * @param {string} url - The API endpoint
 * @param {Object} options - Fetch API options
 * @param {function} successCallback - Function to call on success
 * @param {function} errorCallback - Function to call on error
 */
function callApi(url, options = {}, successCallback, errorCallback) {
  // Set default headers if not provided
  if (!options.headers) {
    options.headers = {
      'Content-Type': 'application/json',
    };
  }

  // Add CSRF token for POST requests if needed
  if (options.method === 'POST' || options.method === 'PUT' || options.method === 'DELETE') {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    if (csrfToken) {
      options.headers['X-CSRFToken'] = csrfToken;
    }
  }

  // Show loading indicator if specified
  let loadingIndicator = null;
  if (options.showLoading) {
    loadingIndicator = showLoadingIndicator(options.loadingElement);
  }

  // Make the API call
  fetch(url, options)
    .then(response => {
      // Remove loading indicator if it exists
      if (loadingIndicator) {
        hideLoadingIndicator(loadingIndicator);
      }

      // Check if response is OK (status in 200-299 range)
      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      }

      // Parse response as JSON or text based on content type
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        return response.json();
      }

      return response.text();
    })
    .then(data => {
      if (successCallback && typeof successCallback === 'function') {
        successCallback(data);
      }
    })
    .catch(error => {
      console.error('API call error:', error);

      // Remove loading indicator if it exists
      if (loadingIndicator) {
        hideLoadingIndicator(loadingIndicator);
      }

      if (errorCallback && typeof errorCallback === 'function') {
        errorCallback(error);
      } else {
        showToast(`Error: ${error.message}`, 'danger');
      }
    });
}

/**
 * Show a loading indicator
 * @param {HTMLElement} element - Element to show the loading indicator in
 * @returns {Object} - References to created elements for later removal
 */
function showLoadingIndicator(element) {
  const targetElement = element || document.body;

  // Create the loading overlay
  const overlay = document.createElement('div');
  overlay.className = 'loading-overlay';
  overlay.style.position = targetElement === document.body ? 'fixed' : 'absolute';
  overlay.style.top = '0';
  overlay.style.left = '0';
  overlay.style.width = '100%';
  overlay.style.height = '100%';
  overlay.style.backgroundColor = 'rgba(255, 255, 255, 0.7)';
  overlay.style.display = 'flex';
  overlay.style.justifyContent = 'center';
  overlay.style.alignItems = 'center';
  overlay.style.zIndex = '9999';

  // Create the spinner
  const spinner = document.createElement('div');
  spinner.className = 'spinner-border text-primary';
  spinner.setAttribute('role', 'status');

  // Create the visually hidden label
  const srText = document.createElement('span');
  srText.className = 'visually-hidden';
  srText.textContent = 'Loading...';

  // Assemble and append to target
  spinner.appendChild(srText);
  overlay.appendChild(spinner);
  targetElement.appendChild(overlay);

  // Store original overflow style
  const originalOverflow = targetElement.style.overflow;
  targetElement.style.overflow = 'hidden';

  return { overlay, originalOverflow, targetElement };
}

/**
 * Hide a previously created loading indicator
 * @param {Object} loadingIndicator - References returned by showLoadingIndicator
 */
function hideLoadingIndicator(loadingIndicator) {
  if (loadingIndicator && loadingIndicator.overlay) {
    loadingIndicator.overlay.remove();
    loadingIndicator.targetElement.style.overflow = loadingIndicator.originalOverflow;
  }
}

/**
 * Format a date string in a localized format
 * @param {string} dateString - ISO date string
 * @param {boolean} includeTime - Whether to include time in the formatted result
 * @returns {string} - Formatted date string
 */
function formatDate(dateString, includeTime = false) {
  if (!dateString) return '';

  const date = new Date(dateString);
  const options = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...(includeTime && { hour: '2-digit', minute: '2-digit' })
  };

  return date.toLocaleDateString(undefined, options);
}

/**
 * Truncate text to a specified length and add ellipsis if needed
 * @param {string} text - Text to truncate
 * @param {number} maxLength - Maximum length
 * @returns {string} - Truncated text
 */
function truncateText(text, maxLength = 100) {
  if (!text) return '';
  if (text.length <= maxLength) return text;

  return text.substring(0, maxLength) + '...';
}

/**
 * Debounce function to limit how often a function can be called
 * @param {function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {function} - Debounced function
 */
function debounce(func, wait = 300) {
  let timeout;

  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };

    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}