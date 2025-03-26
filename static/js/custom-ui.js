/**
 * Custom UI implementation to replace Bootstrap dependency
 * This non-module version attaches all functions to the window object
 */

// Create a global namespace for our custom UI
window.customUI = {};

// Modal implementation
window.customUI.Modal = function(element, config) {
  this.element = element;
  this._config = config || { backdrop: true, keyboard: true, focus: true };

  // Simple show method
  this.show = function() {
    // Create backdrop if needed
    if (this._config.backdrop !== false && !document.querySelector('.modal-backdrop')) {
      const backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop fade show';
      document.body.appendChild(backdrop);

      // Close on backdrop click if not static
      if (this._config.backdrop !== 'static') {
        backdrop.addEventListener('click', () => this.hide());
      }
    }

    // Show modal
    this.element.classList.add('show');
    this.element.style.display = 'block';
    document.body.classList.add('modal-open');

    // Handle escape key
    if (this._config.keyboard) {
      this._escapeHandler = (e) => {
        if (e.key === 'Escape') this.hide();
      };
      document.addEventListener('keydown', this._escapeHandler);
    }

    // Focus first input
    if (this._config.focus) {
      setTimeout(() => {
        const focusable = this.element.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (focusable) focusable.focus();
      }, 100);
    }

    // Trigger shown event
    const event = new CustomEvent('shown.bs.modal');
    this.element.dispatchEvent(event);
  };

  // Simple hide method
  this.hide = function() {
    // Hide modal
    this.element.classList.remove('show');
    this.element.style.display = 'none';
    document.body.classList.remove('modal-open');

    // Remove backdrop
    const backdrop = document.querySelector('.modal-backdrop');
    if (backdrop) {
      backdrop.remove();
    }

    // Remove escape handler
    if (this._escapeHandler) {
      document.removeEventListener('keydown', this._escapeHandler);
    }

    // Trigger hidden event
    const event = new CustomEvent('hidden.bs.modal');
    this.element.dispatchEvent(event);
  };

  // Setup close buttons
  const closeButtons = element.querySelectorAll('[data-bs-dismiss="modal"], [data-dismiss="modal"]');
  closeButtons.forEach(button => {
    button.addEventListener('click', () => this.hide());
  });

  // Store this instance on the element
  element._customModal = this;
};

// Toast implementation
window.customUI.Toast = function(element, config) {
  this.element = element;
  this._config = config || { autohide: true, delay: 5000 };
  this._timeout = null;

  // Simple show method
  this.show = function() {
    this.element.classList.add('show');

    // Auto hide if configured
    if (this._config.autohide) {
      this._timeout = setTimeout(() => {
        this.hide();
      }, this._config.delay);
    }

    // Trigger shown event
    const event = new CustomEvent('shown.bs.toast');
    this.element.dispatchEvent(event);
  };

  // Simple hide method
  this.hide = function() {
    if (this._timeout) {
      clearTimeout(this._timeout);
      this._timeout = null;
    }

    this.element.classList.remove('show');

    // Trigger hidden event
    const event = new CustomEvent('hidden.bs.toast');
    this.element.dispatchEvent(event);

    // Remove if auto-remove is set
    if (this.element.dataset.autoRemove === 'true') {
      setTimeout(() => {
        if (this.element.parentNode) {
          this.element.remove();
        }
      }, 300);
    }
  };

  // Setup close buttons
  const closeButtons = element.querySelectorAll('[data-bs-dismiss="toast"], [data-dismiss="toast"]');
  closeButtons.forEach(button => {
    button.addEventListener('click', () => this.hide());
  });

  // Store instance on element
  element._customToast = this;
};

// Tooltip implementation
window.customUI.Tooltip = function(element, config) {
  this.element = element;
  this._config = config || { placement: 'top', delay: 0 };
  this._tooltipElement = null;

  this.show = function() {
    if (this._tooltipElement) return;

    // Create tooltip element
    this._tooltipElement = document.createElement('div');
    this._tooltipElement.className = 'tooltip fade show';
    this._tooltipElement.setAttribute('role', 'tooltip');

    // Set tooltip content
    const title = this.element.getAttribute('title') ||
                 this.element.getAttribute('data-bs-title') ||
                 this.element.getAttribute('data-original-title') || '';

    this._tooltipElement.innerHTML = `
      <div class="tooltip-arrow"></div>
      <div class="tooltip-inner">${title}</div>
    `;

    // Set element data
    this.element.setAttribute('aria-describedby', 'tooltip');
    this.element.setAttribute('data-original-title', title);
    this.element.removeAttribute('title');

    // Append to body
    document.body.appendChild(this._tooltipElement);

    // Position tooltip
    this._updatePosition();

    // Show with transition
    setTimeout(() => {
      this._tooltipElement.classList.add('show');
    }, 10);
  };

  this.hide = function() {
    if (!this._tooltipElement) return;

    // Remove show class for transition
    this._tooltipElement.classList.remove('show');

    // Remove element after transition
    setTimeout(() => {
      if (this._tooltipElement && this._tooltipElement.parentNode) {
        this._tooltipElement.parentNode.removeChild(this._tooltipElement);
        this._tooltipElement = null;
      }
    }, 300);
  };

  this._updatePosition = function() {
    if (!this._tooltipElement) return;

    const rect = this.element.getBoundingClientRect();
    const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    let top, left;

    // Position based on placement option
    const placement = this._config.placement || 'top';

    switch (placement) {
      case 'top':
        top = rect.top + scrollTop - this._tooltipElement.offsetHeight;
        left = rect.left + scrollLeft + (rect.width / 2) - (this._tooltipElement.offsetWidth / 2);
        break;
      case 'bottom':
        top = rect.top + scrollTop + rect.height;
        left = rect.left + scrollLeft + (rect.width / 2) - (this._tooltipElement.offsetWidth / 2);
        break;
      case 'left':
        top = rect.top + scrollTop + (rect.height / 2) - (this._tooltipElement.offsetHeight / 2);
        left = rect.left + scrollLeft - this._tooltipElement.offsetWidth;
        break;
      case 'right':
        top = rect.top + scrollTop + (rect.height / 2) - (this._tooltipElement.offsetHeight / 2);
        left = rect.left + scrollLeft + rect.width;
        break;
    }

    // Apply position
    this._tooltipElement.style.top = `${top}px`;
    this._tooltipElement.style.left = `${left}px`;

    // Add placement class
    this._tooltipElement.classList.add(`bs-tooltip-${placement}`);
  };

  // Setup event listeners
  this._setupEventListeners = function() {
    this.element.addEventListener('mouseenter', () => this.show());
    this.element.addEventListener('mouseleave', () => this.hide());

    // Handle scroll or resize to reposition
    this._scrollHandler = () => this._updatePosition();
    window.addEventListener('scroll', this._scrollHandler);
    window.addEventListener('resize', this._scrollHandler);
  };

  // Remove event listeners
  this._removeEventListeners = function() {
    this.element.removeEventListener('mouseenter', () => this.show());
    this.element.removeEventListener('mouseleave', () => this.hide());

    if (this._scrollHandler) {
      window.removeEventListener('scroll', this._scrollHandler);
      window.removeEventListener('resize', this._scrollHandler);
    }
  };

  // Initialize
  this._setupEventListeners();

  // Store instance on element
  element._customTooltip = this;
};

// Add getInstance methods
window.customUI.Modal.getInstance = function(element) {
  return element._customModal || null;
};

window.customUI.Toast.getInstance = function(element) {
  return element._customToast || null;
};

window.customUI.Tooltip.getInstance = function(element) {
  return element._customTooltip || null;
};

/**
 * Initialize tooltips on the page
 */
window.initTooltips = function() {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(element => {
    // Skip if already initialized
    if (element._customTooltip) return;

    // Get placement from data attribute
    const placement = element.getAttribute('data-bs-placement') || 'top';

    // Initialize tooltip
    new window.customUI.Tooltip(element, { placement });
  });
};

/**
 * Initialize our custom UI implementation
 */
window.initCustomUIImplementation = function() {
  if (typeof bootstrap === 'undefined') {
    console.log('Bootstrap not found - using custom implementation');
    window.bootstrap = window.customUI;
  } else {
    console.log('Bootstrap found - enhancing with custom fallbacks');
    // Add fallbacks to ensure Bootstrap's methods don't fail
    const originalModalShow = bootstrap.Modal.prototype.show;
    bootstrap.Modal.prototype.show = function() {
      if (!this._config) {
        this._config = { backdrop: true, keyboard: true, focus: true };
      }
      try {
        originalModalShow.call(this);
      } catch (error) {
        console.error('Error in bootstrap Modal show:', error);
        // Use our custom implementation as fallback
        window.customUI.Modal.prototype.show.call(this);
      }
    };
  }

  // Initialize tooltips
  window.initTooltips();
};

// Auto-initialize when the script is loaded
document.addEventListener('DOMContentLoaded', function() {
  window.initCustomUIImplementation();
});