/**
 * Decks Page JavaScript
 * Modern implementation with ES modules and modern patterns
 */

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
  formatDate: (date) => date.toISOString().split('T')[0],

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
    if (!this.container) return;

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
        if (confirm('Are you sure you want to clear all your activity history?')) {
          this.clearActivityData();
        }
      });
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

    // Adjust for European week (Monday first)
    // Convert from JS day (0=Sunday) to European (0=Monday, 6=Sunday)
    let startDay = firstDay.getDay() - 1;
    if (startDay === -1) startDay = 6; // Convert Sunday from -1 to 6

    // Determine if it's a leap year
    const isLeapYear = (this.currentYear % 4 === 0 && this.currentYear % 100 !== 0) || (this.currentYear % 400 === 0);
    const daysInYear = isLeapYear ? 366 : 365;

    // Create all day cells
    let currentDate = new Date(this.currentYear, 0, 1);

    // Adjust for first day of the year
    for (let day = 0; day < daysInYear; day++) {
      // Convert from JS day (0=Sunday) to European (0=Monday, 6=Sunday)
      let dayOfWeek = (startDay + day) % 7;
      const weekNumber = Math.floor((startDay + day) / 7) + 1;

      const cell = document.createElement('div');
      cell.className = 'heatmap-cell activity-level-0';
      cell.setAttribute('role', 'gridcell');

      // Position in grid - add 1 to weekNumber for offset
      cell.style.gridColumn = weekNumber + 1;
      cell.style.gridRow = dayOfWeek + 1;

      // Format date as YYYY-MM-DD for data attribute
      const dateStr = Utils.formatDate(currentDate);
      cell.dataset.date = dateStr;

      // Add accessibility attributes
      cell.setAttribute('aria-label', `${dateStr}: No activity`);

      // Add tooltip
      cell.title = dateStr;

      // Increment date
      currentDate.setDate(currentDate.getDate() + 1);

      this.container.appendChild(cell);
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
    console.log('Updating heatmap with data:', data);

    // Get all heatmap cells
    const cells = document.querySelectorAll('.heatmap-cell');
    console.log(`Found ${cells.length} calendar cells`);

    // Reset all cells to level 0
    cells.forEach(cell => {
      cell.className = 'heatmap-cell activity-level-0';
      const dateStr = cell.dataset.date;
      const displayDate = this.formatDateForDisplay(dateStr);
      cell.setAttribute('aria-label', `${displayDate}: No activity`);
      cell.title = `${displayDate}: No activity`;
    });

    // Keep track of cells updated
    let updatedCells = 0;
    let scheduledCells = 0;
    let activityCells = 0;

    // For each date in the data, update the corresponding cell
    Object.entries(data).forEach(([dateStr, activityData]) => {
      const cell = document.querySelector(`.heatmap-cell[data-date="${dateStr}"]`);
      if (!cell) {
        console.log(`No cell found for date ${dateStr}`);
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

      updatedCells++;

      // Format date for display
      const displayDate = this.formatDateForDisplay(dateStr);

      console.log(`Updating cell for ${dateStr} - reviewed: ${reviewed}, scheduled: ${scheduled}`);

      // Set cell class based on status and count
      if (scheduled > 0) {
        // Scheduled cards - reset all classes and apply ONLY scheduled class
        cell.className = ''; // Remove all classes first
        cell.classList.add('heatmap-cell');
        cell.classList.add('activity-scheduled');
        scheduledCells++;
        console.log(`Cell ${dateStr} marked as scheduled with ${scheduled} cards`);
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
        activityCells++;
        console.log(`Cell ${dateStr} marked as activity level ${level} with ${reviewed} cards`);
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

    console.log(`Updated ${updatedCells} cells total (${activityCells} with activity, ${scheduledCells} with scheduled cards)`);
  }
}

/**
 * Deck Import Manager
 * Handles the import functionality for decks
 */
class DeckImporter {
  constructor() {
    // Main import button
    this.importDeckBtn = document.getElementById('importDeckBtn');

    // Form elements
    this.importTypeSelect = document.getElementById('importType');
    this.fileImportSection = document.getElementById('fileImportSection');
    this.wordsImportSection = document.getElementById('wordsImportSection');
    this.startImportBtn = document.getElementById('startImportBtn');

    // Modals
    this.importDeckModal = new bootstrap.Modal(document.getElementById('importDeckModal'));
    this.importProgressModal = new bootstrap.Modal(document.getElementById('importProgressModal'));
    this.importResultsModal = new bootstrap.Modal(document.getElementById('importResultsModal'));

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
    if (this.importDeckBtn) {
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
   * Handle start import button click
   */
  handleStartImport() {
    const importType = this.importTypeSelect.value;

    // Validate input
    if (importType === 'file') {
      const deckFile = document.getElementById('deckFile');
      const deckName = document.getElementById('deckNameInput').value;

      if (!deckFile.files || deckFile.files.length === 0) {
        this.showAlert('Please select a file to import');
        return;
      }

      if (!deckName) {
        this.showAlert('Please enter a deck name');
        return;
      }

      // Start file import
      this.importDeckModal.hide();
      this.startFileImport(deckFile.files[0], deckName);
    } else {
      const wordsList = document.getElementById('wordsList').value;
      const deckName = document.getElementById('wordsImportDeckName').value;

      if (!wordsList) {
        this.showAlert('Please enter words to import');
        return;
      }

      if (!deckName) {
        this.showAlert('Please enter a deck name');
        return;
      }

      // Start words import
      this.importDeckModal.hide();
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
    this.importProgressModal.show();

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
      this.importProgressModal.hide();

      // Show results
      if (data.success) {
        this.showImportResults(true, `
          <div class="alert alert-success">
            <strong>Import completed successfully!</strong>
          </div>
          <p>Deck "${deckName}" has been created with ${data.imported_count} words.</p>
          <p>There were ${data.error_count} errors during import.</p>
        `);
      } else {
        this.showImportResults(false, `
          <div class="alert alert-danger">
            <strong>Import failed!</strong>
          </div>
          <p>Error: ${data.error}</p>
        `);
      }
    } catch (error) {
      this.importProgressModal.hide();
      this.showImportResults(false, `
        <div class="alert alert-danger">
          <strong>Import failed!</strong>
        </div>
        <p>An unexpected error occurred: ${error.message}</p>
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
    this.importProgressModal.show();

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
      this.importProgressModal.hide();

      // Show results
      if (data.success) {
        this.showImportResults(true, `
          <div class="alert alert-success">
            <strong>Import completed successfully!</strong>
          </div>
          <p>Deck "${deckName}" has been created with ${data.imported_count} words.</p>
          <p>There were ${data.error_count} errors during import.</p>
        `);
      } else {
        this.showImportResults(false, `
          <div class="alert alert-danger">
            <strong>Import failed!</strong>
          </div>
          <p>Error: ${data.error}</p>
        `);
      }
    } catch (error) {
      this.importProgressModal.hide();
      this.showImportResults(false, `
        <div class="alert alert-danger">
          <strong>Import failed!</strong>
        </div>
        <p>An unexpected error occurred: ${error.message}</p>
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
    this.importResultsModal.show();
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
 * App initialization
 * Main entry point for the application
 */
const initApp = () => {
  // Initialize all components
  const heatmap = new ActivityHeatmap();
  const importer = new DeckImporter();
  const animator = new UIAnimator();

  // Start animations
  animator.animateEntrance();

  // App is now fully initialized
};

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', initApp);

// Export classes for testing or reuse
export {
  ActivityHeatmap,
  DeckImporter,
  UIAnimator
};