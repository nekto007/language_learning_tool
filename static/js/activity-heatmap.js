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
      console.error('Heatmap container not found');
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
   * @param {string} key - Translation key
   * @param {string} defaultText - Default text if translation not available
   * @returns {string} Translated text or default
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
   * Format date as YYYY-MM-DD
   * @param {Date} date - Date to format
   * @returns {string} Formatted date string
   */
  formatDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
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

    // Add month labels at the top (optional enhancement)
    const monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const monthLabelRow = document.createElement('div');
    monthLabelRow.className = 'heatmap-month-labels';
    monthLabelRow.style.display = 'grid';
    monthLabelRow.style.gridTemplateColumns = 'repeat(53, 1fr)';
    monthLabelRow.style.marginBottom = '5px';

    let currentMonth = 0;
    let monthStartWeek = 1;

    for (let week = 1; week <= 53; week++) {
      const date = new Date(this.currentYear, 0, (week-1) * 7 + 1);
      const month = date.getMonth();

      if (month !== currentMonth) {
        const monthLabel = document.createElement('div');
        monthLabel.textContent = monthLabels[month];
        monthLabel.style.gridColumn = week;
        monthLabel.style.fontSize = 'var(--font-size-xs)';
        monthLabel.style.color = 'var(--color-secondary)';
        monthLabel.style.textAlign = 'center';
        monthLabelRow.appendChild(monthLabel);

        currentMonth = month;
      }
    }

    this.container.appendChild(monthLabelRow);

    // Create week rows
    const heatmapGrid = document.createElement('div');
    heatmapGrid.className = 'heatmap-days-grid';
    heatmapGrid.style.display = 'grid';
    heatmapGrid.style.gridTemplateColumns = 'repeat(53, 1fr)';
    heatmapGrid.style.gridTemplateRows = 'repeat(7, 1fr)';
    heatmapGrid.style.gap = '3px';

    // Add day labels on the left (optional enhancement)
    const dayLabels = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
    for (let day = 0; day < 7; day++) {
      const dayLabel = document.createElement('div');
      dayLabel.textContent = dayLabels[day];
      dayLabel.style.gridColumn = '1';
      dayLabel.style.gridRow = day + 1;
      dayLabel.style.fontSize = 'var(--font-size-xs)';
      dayLabel.style.color = 'var(--color-secondary)';
      dayLabel.style.marginRight = '5px';
      dayLabel.style.display = 'flex';
      dayLabel.style.alignItems = 'center';
      dayLabel.style.justifyContent = 'center';
      heatmapGrid.appendChild(dayLabel);
    }

    // Adjust for first day of the year
    for (let day = 0; day < daysInYear; day++) {
      // Convert from JS day (0=Sunday) to European (0=Monday, 6=Sunday)
      let dayOfWeek = currentDate.getDay() - 1;
      if (dayOfWeek === -1) dayOfWeek = 6; // Convert Sunday from -1 to 6

      const weekNumber = Math.floor(day / 7) + 2; // +2 because we have labels in column 1

      const cell = document.createElement('div');
      cell.className = 'heatmap-cell activity-level-0';
      cell.setAttribute('role', 'gridcell');

      // Position in grid
      cell.style.gridColumn = weekNumber;
      cell.style.gridRow = dayOfWeek + 1;
      cell.style.width = '12px';
      cell.style.height = '12px';
      cell.style.borderRadius = '2px';
      cell.style.transition = 'background-color 0.2s, transform 0.2s';

      // Format date as YYYY-MM-DD for data attribute
      const dateStr = this.formatDate(currentDate);
      cell.dataset.date = dateStr;

      // Add accessibility attributes
      cell.setAttribute('aria-label', `${dateStr}: No activity`);

      // Add tooltip
      cell.title = dateStr;

      // Increment date
      currentDate.setDate(currentDate.getDate() + 1);

      heatmapGrid.appendChild(cell);
    }

    this.container.appendChild(heatmapGrid);
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
      cell.style.backgroundColor = 'var(--activity-0)';
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
        cell.style.backgroundColor = 'var(--activity-0)';
        cell.style.border = '2px dashed var(--color-primary)';
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
        cell.style.backgroundColor = `var(--activity-${level})`;
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

export { ActivityHeatmap };