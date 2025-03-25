/**
 * Statistics Page JavaScript
 * Modern implementation with ES6+ features
 * Fixed Chart.js initialization
 */

document.addEventListener('DOMContentLoaded', () => {
  // Init charts and components
  initActivityChart();
  initStatusChart();
  initActivityFilter();
  initAnimate();
});

/**
 * Initialize the activity chart showing daily review counts
 */
const initActivityChart = () => {
  const chartElement = document.getElementById('activityChart');

  // Check if element exists and is a canvas
  if (!chartElement || !(chartElement instanceof HTMLCanvasElement)) {
    console.error('Activity chart element not found or not a canvas element');
    return;
  }

  // Process data for chart
  const dates = [];
  const counts = [];

  // Get last 30 days
  const today = new Date();

  // Create map for easy lookup
  const sessionsMap = {};

  // Check if sessionData is available from the template
  if (typeof sessionData === 'undefined') {
    console.error('Session data not available');
    return;
  }

  sessionData.forEach(session => {
    if (!session || !session.session_date) return;

    try {
      const date = new Date(session.session_date);
      const dateStr = `${date.getFullYear()}-${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')}`;
      sessionsMap[dateStr] = session.cards_reviewed || 0;
    } catch (e) {
      console.error('Error processing session data:', e);
    }
  });

  // Fill in all dates for the last 30 days
  for (let i = 29; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(today.getDate() - i);

    const dateStr = `${date.getFullYear()}-${(date.getMonth() + 1).toString().padStart(2, '0')}-${date.getDate().toString().padStart(2, '0')}`;
    const formattedDate = `${date.getDate().toString().padStart(2, '0')}.${(date.getMonth() + 1).toString().padStart(2, '0')}`;

    dates.push(formattedDate);
    counts.push(sessionsMap[dateStr] || 0);
  }

  // Calculate max value for better Y-axis scaling
  const maxCount = Math.max(...counts, 1);
  const yAxisMax = Math.ceil(maxCount * 1.2); // 20% headroom

  try {
    // Create chart
    const ctx = chartElement.getContext('2d');
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [{
          label: 'Cards Reviewed',
          data: counts,
          backgroundColor: 'rgba(13, 110, 253, 0.6)',
          borderColor: 'rgba(13, 110, 253, 1)',
          borderWidth: 1,
          borderRadius: 4,
          barThickness: 8,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            callbacks: {
              title: (tooltipItems) => {
                const date = tooltipItems[0].label;
                return `Date: ${date}`;
              },
              label: (context) => {
                const count = context.raw;
                return `Cards: ${count}`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            suggestedMax: yAxisMax,
            ticks: {
              precision: 0
            },
            grid: {
              display: true,
              color: 'rgba(0, 0, 0, 0.05)'
            }
          },
          x: {
            grid: {
              display: false
            },
            ticks: {
              maxRotation: 45,
              minRotation: 45,
              callback: function(value, index, values) {
                // Show fewer labels on smaller screens
                const screenWidth = window.innerWidth;
                if (screenWidth < 768) {
                  return index % 5 === 0 ? this.getLabelForValue(value) : '';
                } else if (screenWidth < 992) {
                  return index % 3 === 0 ? this.getLabelForValue(value) : '';
                }
                return this.getLabelForValue(value);
              }
            }
          }
        }
      }
    });
  } catch (e) {
    console.error('Error creating activity chart:', e);
    // Fallback message
    chartElement.parentElement.innerHTML = `
      <div class="alert alert-warning">
        <i class="bi bi-exclamation-triangle me-2"></i>
        Unable to load activity chart. Please try refreshing the page.
      </div>
    `;
  }
};

/**
 * Initialize the status breakdown chart
 */
const initStatusChart = () => {
  const chartElement = document.getElementById('statusChart');

  // Check if element exists and is a canvas
  if (!chartElement || !(chartElement instanceof HTMLCanvasElement)) {
    console.error('Status chart element not found or not a canvas element');
    return;
  }

  // Check if statusCounts is available from the template
  if (typeof statusCounts === 'undefined') {
    console.error('Status data not available');
    return;
  }

  // Prepare data for chart
  const labels = Object.keys(statusCounts);
  const data = Object.values(statusCounts);

  // Skip rendering if all values are 0
  if (data.every(value => value === 0)) {
    const parent = chartElement.parentElement;
    if (parent) {
      parent.innerHTML = `
        <div class="text-center py-4">
          <div class="text-muted">No word data available yet</div>
        </div>
      `;
    }
    return;
  }

  // Define colors based on our status system
  const backgroundColors = [
    '#6c757d', // New - Gray
    '#0d6efd', // Studying - Blue
    '#198754'  // Studied - Green
  ];

  try {
    // Create chart
    const ctx = chartElement.getContext('2d');
    new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: backgroundColors,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              usePointStyle: true,
              padding: 15
            }
          },
          tooltip: {
            callbacks: {
              label: (context) => {
                const label = context.label || '';
                const value = context.raw;
                const total = context.dataset.data.reduce((acc, val) => acc + val, 0);
                const percentage = Math.round((value / total) * 100);
                return `${label}: ${value} (${percentage}%)`;
              }
            }
          }
        }
      }
    });
  } catch (e) {
    console.error('Error creating status chart:', e);
    // Fallback message
    chartElement.parentElement.innerHTML = `
      <div class="alert alert-warning">
        <i class="bi bi-exclamation-triangle me-2"></i>
        Unable to load status chart. Please try refreshing the page.
      </div>
    `;
  }
};

/**
 * Initialize the activity filter dropdown
 */
const initActivityFilter = () => {
  const periodSelect = document.getElementById('activityPeriod');
  if (!periodSelect) return;

  // Apply filter on dropdown change
  periodSelect.addEventListener('change', () => {
    const days = parseInt(periodSelect.value);
    filterActivity(days);
  });

  // Apply initial filter
  const initialDays = parseInt(periodSelect.value);
  filterActivity(initialDays);
};

/**
 * Filter activity table by date period
 * @param {number} days - Number of days to show
 */
const filterActivity = (days) => {
  // Get all rows in the table
  const rows = document.querySelectorAll('table tbody tr');
  if (!rows.length) return;

  const today = new Date();
  const cutoffDate = new Date();
  cutoffDate.setDate(today.getDate() - days);

  // Track visible rows for empty state
  let visibleRows = 0;

  // Show or hide rows based on date
  rows.forEach(row => {
    const dateCell = row.cells[0].textContent;
    const dateParts = dateCell.split('.');
    if (dateParts.length !== 3) return;

    try {
      const rowDate = new Date(`${dateParts[2]}-${dateParts[1]}-${dateParts[0]}`);

      if (rowDate >= cutoffDate) {
        row.style.display = '';
        visibleRows++;
      } else {
        row.style.display = 'none';
      }
    } catch (e) {
      console.error('Error parsing date:', e);
    }
  });

  // Show empty state if no visible rows
  const tableBody = rows[0]?.parentElement;
  if (!tableBody) return;

  const existingMessage = tableBody.querySelector('.no-data-message');

  if (visibleRows === 0) {
    if (!existingMessage) {
      const messageRow = document.createElement('tr');
      messageRow.className = 'no-data-message';
      messageRow.innerHTML = `
        <td colspan="3" class="text-center py-4">
          <div class="text-muted">No activity data for the selected period</div>
        </td>
      `;
      tableBody.appendChild(messageRow);
    }
  } else if (existingMessage) {
    existingMessage.remove();
  }
};

/**
 * Initialize animations for statistics cards
 */
const initAnimate = () => {
  // Reset animation for cards (in case CSS animations don't work)
  const elements = [
    ...document.querySelectorAll('.stat-card'),
    ...document.querySelectorAll('.stats-card')
  ];

  elements.forEach((element, index) => {
    element.style.opacity = '0';
    element.style.transform = 'translateY(20px)';

    setTimeout(() => {
      element.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      element.style.opacity = '1';
      element.style.transform = 'translateY(0)';
    }, 100 + (index * 100));
  });
};