/**
 * Decks Page JavaScript
 * Modern implementation with ES modules and modern patterns
 */

// Import the language manager
import { LanguageManager } from './language-manager.js';

// Utility functions
const Utils = {
  /**
   * Wait for the specified milliseconds
   * @param {number} ms - Milliseconds to wait
   * @returns {Promise} Promise that resolves after the delay
   */
  delay: (ms) => new Promise(resolve => setTimeout(resolve, ms)),

  /**
   * Format date as YYYY-MM-DD
   * @param {Date} date - Date to format
   * @returns {string} Formatted date string
   */
  formatDate: (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  },

  /**
   * Toggle element visibility
   * @param {HTMLElement} element - Element to toggle
   * @param {boolean} show - Whether to show the element
   */
  toggleVisibility: (element, show) => {
    if (!element) return;
    element.style.display = show ? '' : 'none';
  },

  /**
   * Add animation class and remove it after animation completes
   * @param {HTMLElement} element - Element to animate
   * @param {string} animationClass - CSS class for animation
   */
  animateElement: async (element, animationClass) => {
    if (!element) return;
    element.classList.add(animationClass);
    await Utils.delay(500); // Wait for animation to complete
    element.classList.remove(animationClass);
  }
};

/**
 * Activity Heatmap Calendar Class
 * Handles rendering and updating the activity calendar
 */
class ActivityHeatmap {
  constructor(containerId = 'heatmap-grid') {
    this.container = document.getElementById(containerId);
    this.currentYear = new Date().getFullYear();
    this.yearDisplay = document.getElementById('currentYear');
    this.prevYearBtn = document.getElementById('prevYearBtn');
    this.nextYearBtn = document.getElementById('nextYearBtn');
    this.clearActivityBtn = document.getElementById('clearActivityBtn');

    this.init();
  }

  /**
   * Initialize the heatmap and attach event listeners
   */
  init() {
    if (!this.container) {
      console.warn('Heatmap container not found');
      return;
    }

    // Set current year display
    if (this.yearDisplay) {
      this.yearDisplay.textContent = this.currentYear;
    }

    // Render initial heatmap
    this.render();

    // Fetch initial activity data
    this.fetchData();

    // Attach event listeners
    this.attachEventListeners();
  }

  /**
   * Attach event listeners for year navigation
   */
  attachEventListeners() {
    const thisYear = new Date().getFullYear();

    // Disable next year button if we're at the current year
    if (this.nextYearBtn && this.currentYear >= thisYear) {
      this.nextYearBtn.disabled = true;
    }

    // Previous year button
    if (this.prevYearBtn) {
      this.prevYearBtn.addEventListener('click', () => {
        this.currentYear--;

        if (this.yearDisplay) {
          this.yearDisplay.textContent = this.currentYear;
        }

        // Enable next year button if we're going back
        if (this.nextYearBtn) {
          this.nextYearBtn.disabled = false;
        }

        // Update heatmap for new year
        this.render();
        this.fetchData();
      });
    }

    // Next year button
    if (this.nextYearBtn) {
      this.nextYearBtn.addEventListener('click', () => {
        this.currentYear++;

        if (this.yearDisplay) {
          this.yearDisplay.textContent = this.currentYear;
        }

        // Disable next year button if we've reached the current year
        if (this.currentYear >= thisYear && this.nextYearBtn) {
          this.nextYearBtn.disabled = true;
        }

        // Update heatmap for new year
        this.render();
        this.fetchData();
      });
    }

    // Clear activity button
    if (this.clearActivityBtn) {
      this.clearActivityBtn.addEventListener('click', () => {
        const message = this.getTranslation ?
                       this.getTranslation('clearConfirmation', 'Are you sure you want to clear all your activity history?') :
                       'Are you sure you want to clear all your activity history?';

        if (confirm(message)) {
          this.clearActivityData();
        }
      });
    }
  }

  /**
   * Get translation if available
   */
  getTranslation(key, defaultText) {
    try {
      // Check if language manager is available in global scope
      if (window.languageManager && typeof window.languageManager.translate === 'function') {
        return window.languageManager.translate(key);
      }
      return defaultText;
    } catch (e) {
      return defaultText;
    }
  }

  /**
   * Clear all activity data
   */
  async clearActivityData() {
    try {
      const response = await fetch('/srs/api/activity/clear', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      if (response.ok) {
        const result = await response.json();
        // Show success message
        alert(result.message || 'Activity history cleared successfully');
        // Refresh the heatmap
        this.fetchData();
      } else {
        alert('Failed to clear activity data');
      }
    } catch (error) {
      console.error('Error clearing activity data:', error);
      alert('An error occurred while clearing activity data');
    }
  }

  /**
   * Render the heatmap grid for the current year
   */
  render() {
    if (!this.container) return;

    // Clear existing grid
    this.container.innerHTML = '';

    // Create first day of the year
    const firstDay = new Date(this.currentYear, 0, 1);

    // Get day of week offset (0 = Sunday, 1 = Monday, etc.)
    let startDayOfWeek = firstDay.getDay();
    if (startDayOfWeek === 0) startDayOfWeek = 7; // Make Sunday the 7th day

    // Determine if it's a leap year
    const isLeapYear = (this.currentYear % 4 === 0 && this.currentYear % 100 !== 0) || (this.currentYear % 400 === 0);
    const daysInYear = isLeapYear ? 366 : 365;

    // Calculate number of weeks
    const numWeeks = Math.ceil((daysInYear + startDayOfWeek - 1) / 7);

    // Set up grid style
    this.container.style.display = 'grid';
    this.container.style.gridTemplateColumns = `repeat(${numWeeks}, 1fr)`;
    this.container.style.gridTemplateRows = 'repeat(7, 1fr)';
    this.container.style.gap = '3px';

    // Create all day cells
    let currentDate = new Date(this.currentYear, 0, 1);

    for (let i = 0; i < daysInYear; i++) {
      const dayOfWeek = currentDate.getDay(); // 0-6 (Sunday-Saturday)
      const adjustedDayOfWeek = dayOfWeek === 0 ? 6 : dayOfWeek - 1; // 0-6 (Monday-Sunday)

      // Calculate week number (0-based)
      const weekNum = Math.floor((i + startDayOfWeek - 1) / 7);

      const cell = document.createElement('div');
      cell.className = 'heatmap-cell activity-level-0';

      // Set position in grid
      cell.style.gridRow = adjustedDayOfWeek + 1;
      cell.style.gridColumn = weekNum + 1;

      // Style the cell
      cell.style.width = '12px';
      cell.style.height = '12px';
      cell.style.borderRadius = '2px';
      cell.style.backgroundColor = 'var(--activity-0, #ebedf0)';

      // Store date data
      const dateStr = Utils.formatDate(currentDate);
      cell.dataset.date = dateStr;

      // Accessibility
      cell.setAttribute('role', 'gridcell');
      cell.setAttribute('aria-label', `${dateStr}: No activity`);
      cell.title = dateStr;

      // Add to grid
      this.container.appendChild(cell);

      // Move to next day
      currentDate.setDate(currentDate.getDate() + 1);
    }
  }

  /**
   * Fetch activity data for the current year
   */
  async fetchData() {
    try {
      console.log(`Fetching activity data for ${this.currentYear}`);
      const response = await fetch(`/srs/api/activity/${this.currentYear}`);

      if (response.ok) {
        const data = await response.json();
        console.log(`Received activity data with ${Object.keys(data).length} entries`);
        this.updateHeatmap(data);
      } else {
        console.warn(`Failed to fetch activity data: ${response.status}`);
        this.updateHeatmap({});
      }
    } catch (error) {
      console.error('Error fetching activity data:', error);
      this.updateHeatmap({});
    }
  }

  /**
   * Format date for display in tooltips
   * @param {string} dateStr - ISO date string (YYYY-MM-DD)
   * @returns {string} Formatted date
   */
  formatDateForDisplay(dateStr) {
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString(undefined, {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
    } catch (e) {
      return dateStr;
    }
  }

  /**
   * Update the heatmap with activity data
   * @param {Object} data - Activity data object
   */
  updateHeatmap(data) {
    // Get all heatmap cells
    const cells = document.querySelectorAll('.heatmap-cell');

    if (!cells.length) {
      console.warn('No heatmap cells found to update');
      return;
    }

    // Reset all cells to level 0
    cells.forEach(cell => {
      cell.className = 'heatmap-cell activity-level-0';
      cell.style.backgroundColor = 'var(--activity-0, #ebedf0)';
      cell.style.border = 'none';
      const dateStr = cell.dataset.date;
      const displayDate = this.formatDateForDisplay(dateStr);
      cell.setAttribute('aria-label', `${displayDate}: No activity`);
      cell.title = `${displayDate}: No activity`;
    });

    // For each date in the data, update the corresponding cell
    Object.entries(data).forEach(([dateStr, activityData]) => {
      const cell = document.querySelector(`.heatmap-cell[data-date="${dateStr}"]`);
      if (!cell) {
        return;
      }

      // Get data values with defaults if properties are missing
      const reviewed = parseInt(activityData.reviewed || 0);
      const scheduled = parseInt(activityData.scheduled || 0);
      const minutes = parseInt(activityData.minutes || 0);

      // Skip if no activity and no scheduled cards
      if (reviewed === 0 && scheduled === 0) {
        return;
      }

      // Format date for display
      const displayDate = this.formatDateForDisplay(dateStr);

      // Set cell class based on status and count
      if (scheduled > 0) {
        // Scheduled cards
        cell.className = 'heatmap-cell activity-scheduled';
        cell.style.backgroundColor = 'var(--activity-0, #ebedf0)';
        cell.style.border = '2px dashed var(--color-primary, #0d6efd)';
        cell.style.boxSizing = 'border-box';
      }
      else if (reviewed > 0) {
        // Completed cards - level based on count
        let level = 0;
        if (reviewed > 0 && reviewed < 10) level = 1;
        else if (reviewed >= 10 && reviewed < 20) level = 2;
        else if (reviewed >= 20 && reviewed < 30) level = 3;
        else if (reviewed >= 30 && reviewed < 50) level = 4;
        else if (reviewed >= 50) level = 5;

        cell.className = `heatmap-cell activity-level-${level}`;

        // Set color based on level
        const colors = {
          1: 'var(--activity-1, #9be9a8)',
          2: 'var(--activity-2, #40c463)',
          3: 'var(--activity-3, #30a14e)',
          4: 'var(--activity-4, #216e39)',
          5: 'var(--activity-5, #0d4e24)'
        };

        cell.style.backgroundColor = colors[level] || colors[1];
        cell.style.border = 'none';
      }

      // Create tooltip text
      let tooltipText = `${displayDate}: `;
      let tooltipParts = [];

      if (reviewed > 0) {
        tooltipParts.push(`${reviewed} cards reviewed`);
        if (minutes > 0) {
          tooltipParts.push(`${minutes} minutes`);
        }
      }

      if (scheduled > 0) {
        tooltipParts.push(`${scheduled} cards scheduled`);
      }

      tooltipText += tooltipParts.join(', ');

      // Update accessibility attributes
      cell.setAttribute('aria-label', tooltipText);

      // Update tooltip
      cell.title = tooltipText;
    });
  }
}

/**
 * Deck Import Manager
 * Handles the import functionality for decks
 */
class DeckImporter {
  constructor(languageManager) {
    this.languageManager = languageManager;

    // Main import button
    this.importDeckBtn = document.getElementById('importDeckBtn');

    // Form elements
    this.importTypeSelect = document.getElementById('importType');
    this.fileImportSection = document.getElementById('fileImportSection');
    this.wordsImportSection = document.getElementById('wordsImportSection');
    this.startImportBtn = document.getElementById('startImportBtn');

    // Modals - with error handling for missing bootstrap
    try {
      this.importDeckModal = new bootstrap.Modal(document.getElementById('importDeckModal'));
      this.importProgressModal = new bootstrap.Modal(document.getElementById('importProgressModal'));
      this.importResultsModal = new bootstrap.Modal(document.getElementById('importResultsModal'));
    } catch (error) {
      console.warn('Bootstrap not available or modal elements missing:', error);
      this.importDeckModal = null;
      this.importProgressModal = null;
      this.importResultsModal = null;
    }

    this.init();
  }

  /**
   * Initialize event listeners
   */
  init() {
    // Change import type
    if (this.importTypeSelect) {
      this.importTypeSelect.addEventListener('change', () => {
        const importType = this.importTypeSelect.value;
        Utils.toggleVisibility(this.fileImportSection, importType === 'file');
        Utils.toggleVisibility(this.wordsImportSection, importType === 'words');
      });
    }

    // Open import modal
    if (this.importDeckBtn && this.importDeckModal) {
      this.importDeckBtn.addEventListener('click', () => {
        this.importDeckModal.show();
      });
    }

    // Start import process
    if (this.startImportBtn) {
      this.startImportBtn.addEventListener('click', () => this.handleStartImport());
    }

    // Import results OK button
    const importResultsOkBtn = document.getElementById('importResultsOkBtn');
    if (importResultsOkBtn) {
      importResultsOkBtn.addEventListener('click', () => {
        // Reload the page to show the new deck
        window.location.reload();
      });
    }
  }

  /**
   * Get translation using language manager
   */
  translate(key, defaultText) {
    if (this.languageManager && typeof this.languageManager.translate === 'function') {
      return this.languageManager.translate(key) || defaultText;
    }
    return defaultText;
  }

  /**
   * Handle start import button click
   */
  handleStartImport() {
    const importType = this.importTypeSelect ? this.importTypeSelect.value : 'file';

    // Validate input
    if (importType === 'file') {
      const deckFile = document.getElementById('deckFile');
      const deckName = document.getElementById('deckNameInput') ? document.getElementById('deckNameInput').value : '';

      if (!deckFile || !deckFile.files || deckFile.files.length === 0) {
        this.showAlert(this.translate('pleaseSelectFile', 'Please select a file to import'));
        return;
      }

      if (!deckName) {
        this.showAlert(this.translate('pleaseEnterDeckName', 'Please enter a deck name'));
        return;
      }

      // Start file import
      if (this.importDeckModal) {
        this.importDeckModal.hide();
      }
      this.startFileImport(deckFile.files[0], deckName);
    } else {
      const wordsListElement = document.getElementById('wordsList');
      const deckNameElement = document.getElementById('wordsImportDeckName');

      if (!wordsListElement || !deckNameElement) {
        this.showAlert('Form elements not found');
        return;
      }

      const wordsList = wordsListElement.value;
      const deckName = deckNameElement.value;

      if (!wordsList) {
        this.showAlert(this.translate('pleaseEnterWords', 'Please enter words to import'));
        return;
      }

      if (!deckName) {
        this.showAlert(this.translate('pleaseEnterDeckName', 'Please enter a deck name'));
        return;
      }

      // Start words import
      if (this.importDeckModal) {
        this.importDeckModal.hide();
      }
      this.startWordsImport(wordsList, deckName);
    }
  }

  /**
   * Show an alert message
   * @param {string} message - The message to display
   */
  showAlert(message) {
    alert(message); // Using browser alert for simplicity
  }

  /**
   * Start file import process
   * @param {File} file - The file to import
   * @param {string} deckName - The name for the new deck
   */
  async startFileImport(file, deckName) {
    // Show progress modal
    if (this.importProgressModal) {
      this.importProgressModal.show();
    }

    try {
      // Create form data
      const formData = new FormData();
      formData.append('file', file);
      formData.append('deck_name', deckName);

      // Send import request
      const response = await fetch('/srs/api/import/file', {
        method: 'POST',
        body: formData
      });

      const data = await response.json();

      if (this.importProgressModal) {
        this.importProgressModal.hide();
      }

      // Show results
      if (data.success) {
        const importCompleted = this.translate('importCompleted', 'Import completed successfully!');
        this.showImportResults(true, `
          <div class="alert alert-success">
            <strong>${importCompleted}</strong>
          </div>
          <p>Deck "${deckName}" has been created with ${data.imported_count} words.</p>
          <p>There were ${data.error_count} errors during import.</p>
        `);
      } else {
        const importFailed = this.translate('importFailed', 'Import failed!');
        this.showImportResults(false, `
          <div class="alert alert-danger">
            <strong>${importFailed}</strong>
          </div>
          <p>Error: ${data.error}</p>
        `);
      }
    } catch (error) {
      if (this.importProgressModal) {
        this.importProgressModal.hide();
      }

      const importFailed = this.translate('importFailed', 'Import failed!');
      const unexpectedError = this.translate('unexpectedError', 'An unexpected error occurred');

      this.showImportResults(false, `
        <div class="alert alert-danger">
          <strong>${importFailed}</strong>
        </div>
        <p>${unexpectedError}: ${error.message}</p>
      `);
    }
  }

  /**
   * Start words list import process
   * @param {string} wordsList - The words to import
   * @param {string} deckName - The name for the new deck
   */
  async startWordsImport(wordsList, deckName) {
    // Show progress modal
    if (this.importProgressModal) {
      this.importProgressModal.show();
    }

    try {
      // Parse words list
      const words = wordsList.split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0);

      // Send import request
      const response = await fetch('/srs/api/import/words_list', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          deck_name: deckName,
          words: words
        })
      });

      const data = await response.json();

      if (this.importProgressModal) {
        this.importProgressModal.hide();
      }

      // Show results
      if (data.success) {
        const importCompleted = this.translate('importCompleted', 'Import completed successfully!');
        this.showImportResults(true, `
          <div class="alert alert-success">
            <strong>${importCompleted}</strong>
          </div>
          <p>Deck "${deckName}" has been created with ${data.imported_count} words.</p>
          <p>There were ${data.error_count} errors during import.</p>
        `);
      } else {
        const importFailed = this.translate('importFailed', 'Import failed!');
        this.showImportResults(false, `
          <div class="alert alert-danger">
            <strong>${importFailed}</strong>
          </div>
          <p>Error: ${data.error}</p>
        `);
      }
    } catch (error) {
      if (this.importProgressModal) {
        this.importProgressModal.hide();
      }

      const importFailed = this.translate('importFailed', 'Import failed!');
      const unexpectedError = this.translate('unexpectedError', 'An unexpected error occurred');

      this.showImportResults(false, `
        <div class="alert alert-danger">
          <strong>${importFailed}</strong>
        </div>
        <p>${unexpectedError}: ${error.message}</p>
      `);
    }
  }

  /**
   * Show import results modal
   * @param {boolean} success - Whether import was successful
   * @param {string} content - HTML content to display
   */
  showImportResults(success, content) {
    const resultsContent = document.getElementById('importResultsContent');
    if (resultsContent) {
      resultsContent.innerHTML = content;
    }

    if (this.importResultsModal) {
      this.importResultsModal.show();
    }
  }
}

/**
 * UI Animation Manager
 * Handles animations for UI elements
 */
class UIAnimator {
  constructor() {
    this.elements = {
      decksTable: document.querySelector('.decks-table'),
      statsCards: document.querySelectorAll('.stats-card'),
      emptyState: document.querySelector('.empty-state'),
      calendar: document.querySelector('.activity-calendar')
    };
  }

  /**
   * Animate elements with staggered entrance
   */
  animateEntrance() {
    // Create array of elements to animate
    const animatableElements = [
      this.elements.decksTable,
      ...this.elements.statsCards,
      this.elements.emptyState,
      this.elements.calendar
    ].filter(elem => elem !== null);

    // Apply animations with staggered delay
    animatableElements.forEach((element, index) => {
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
}

/**
 * Fix column headers alignment
 */
function fixTableCellAlignment() {
  // Add CSS class to fix layout
  const style = document.createElement('style');
  style.textContent = `
    /* Table structure */
    .decks-table {
      display: table;
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
    }
    
    .decks-table__header {
      display: table-header-group;
    }
    
    .decks-table__header > div {
      display: table-row;
    }
    
    .decks-table [role="rowgroup"]:last-child {
      display: table-row-group;
    }
    
    .decks-table__row {
      display: table-row;
    }
    
    /* Cell alignment */
    .decks-table__header [role="columnheader"],
    .decks-table__row [role="cell"] {
      display: table-cell;
      text-align: center;
      vertical-align: middle;
      box-sizing: border-box;
    }
    
    /* Column widths */
    .deck-name {
      width: 70%;
      text-align: left !important;
    }
    
    .deck-new, .deck-studying, .deck-due {
      width: 10%;
      text-align: center !important;
    }
    
    /* Force numeric alignment */
    .decks-table__row .deck-new,
    .decks-table__row .deck-studying,
    .decks-table__row .deck-due {
      text-align: center !important;
    }
    
    /* Heatmap fixes */
    .heatmap-cell {
      width: 12px !important;
      height: 12px !important;
      border-radius: 2px !important;
      transition: transform 0.2s !important;
    }
    
    .heatmap-cell:hover {
      transform: scale(1.5) !important;
      z-index: 1 !important;
    }
    
    /* Activity levels */
    .activity-level-0 { background-color: #ebedf0 !important; }
    .activity-level-1 { background-color: #9be9a8 !important; }
    .activity-level-2 { background-color: #40c463 !important; }
    .activity-level-3 { background-color: #30a14e !important; }
    .activity-level-4 { background-color: #216e39 !important; }
    .activity-level-5 { background-color: #0d4e24 !important; }
    
    .activity-scheduled {
      background-color: #ebedf0 !important;
      border: 2px dashed #0d6efd !important;
      box-sizing: border-box !important;
    }
  `;
  document.head.appendChild(style);

  // Apply direct DOM fixes to ensure cell alignment
  const cells = document.querySelectorAll('.decks-table__row [role="cell"]');
  cells.forEach(cell => {
    if (cell.classList.contains('deck-name')) {
      cell.style.textAlign = 'left';
      cell.style.width = '70%';
    } else if (cell.classList.contains('deck-new') ||
              cell.classList.contains('deck-studying') ||
              cell.classList.contains('deck-due')) {
      cell.style.textAlign = 'center';
      cell.style.width = '10%';
    }
  });

  // Fix header alignment
  const headers = document.querySelectorAll('.decks-table__header [role="columnheader"]');
  headers.forEach(header => {
    if (header.classList.contains('deck-name')) {
      header.style.textAlign = 'left';
      header.style.width = '70%';
    } else if (header.classList.contains('deck-new') ||
              header.classList.contains('deck-studying') ||
              header.classList.contains('deck-due')) {
      header.style.textAlign = 'center';
      header.style.width = '10%';
    }
  });

  console.log('Table cell alignment fixed');
}

/**
 * App initialization
 * Main entry point for the application
 */
const initApp = () => {
  try {
    // Fix table alignment first
    fixTableCellAlignment();

    // Initialize language manager
    const languageManager = new LanguageManager();

    // Make language manager globally available
    window.languageManager = languageManager;

    // Initialize all components
    const activityHeatmap = new ActivityHeatmap();
    const importer = new DeckImporter(languageManager);
    const animator = new UIAnimator();

    // Start animations
    animator.animateEntrance();

    // App is now fully initialized
    console.log('Application initialized with language: ' + languageManager.currentLang);
  } catch (error) {
    console.error('Error initializing application:', error);
  }
};

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', initApp);

// Export classes for testing or reuse
export {
  ActivityHeatmap,
  DeckImporter,
  UIAnimator,
  LanguageManager
};