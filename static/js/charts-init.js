/**
 * Dashboard charts initialization for Language Learning Tool
 * Handles creation and display of statistics charts
 */

/**
 * Initialize the status distribution doughnut chart
 * @param {Object} labels - Status label mapping
 * @param {Object} stats - Data for each status
 */
function initStatusChart(labels, stats) {
  const ctx = document.getElementById('statusChart')?.getContext('2d');
  if (!ctx) return;

  // Prepare labels and data arrays
  const statusLabels = [];
  const statusData = [];
  const backgroundColors = [
    'rgba(108, 117, 125, 0.8)',  // New - gray
    'rgba(40, 167, 69, 0.8)',    // Known - green
    'rgba(23, 162, 184, 0.8)',   // Queued - info
    'rgba(0, 123, 255, 0.8)',    // Active - primary
    'rgba(255, 193, 7, 0.8)',    // Mastered - warning
  ];
  const borderColors = [
    'rgb(108, 117, 125)',  // New - gray
    'rgb(40, 167, 69)',    // Known - green
    'rgb(23, 162, 184)',   // Queued - info
    'rgb(0, 123, 255)',    // Active - primary
    'rgb(255, 193, 7)',    // Mastered - warning
  ];

  // Fill arrays with data
  Object.keys(labels).forEach((statusId, index) => {
    statusLabels.push(labels[statusId]);
    statusData.push(stats[statusId] || 0);
  });

  // Create chart
  const chart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: statusLabels,
      datasets: [{
        data: statusData,
        backgroundColor: backgroundColors,
        borderColor: borderColors,
        borderWidth: 1,
        hoverOffset: 5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '70%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            padding: 20,
            usePointStyle: true,
            pointStyle: 'circle'
          }
        },
        tooltip: {
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          padding: 12,
          titleFont: {
            size: 14,
            weight: 'bold'
          },
          bodyFont: {
            size: 13
          },
          callbacks: {
            label: function(context) {
              const label = context.label || '';
              const value = context.raw || 0;
              const total = context.dataset.data.reduce((a, b) => a + b, 0);
              const percentage = Math.round((value / total) * 100);
              return `${label}: ${value} (${percentage}%)`;
            }
          }
        }
      },
      animation: {
        animateScale: true,
        animateRotate: true
      }
    }
  });

  // Add center text with total word count
  addChartCenterText();
}

/**
 * Add center text to the doughnut chart
 */
function addChartCenterText() {
  const chartContainer = document.querySelector('.chart-container');
  if (!chartContainer) return;

  // Calculate total words
  let totalWords = 0;
  const stats = window.dashboardStats || {};

  Object.values(stats).forEach(value => {
    totalWords += (typeof value === 'number') ? value : 0;
  });

  if (totalWords > 0) {
    // Create and add center text element
    const centerText = document.createElement('div');
    centerText.className = 'chart-center-text';
    centerText.innerHTML = `
      <div class="chart-center-value">${totalWords}</div>
      <div class="chart-center-label">Total Words</div>
    `;
    chartContainer.appendChild(centerText);
  }
}

/**
 * Initialize charts when document is ready
 */
document.addEventListener('DOMContentLoaded', function() {
  // Initialize the status chart if data is available
  if (window.statusLabels && window.dashboardStats) {
    initStatusChart(window.statusLabels, window.dashboardStats);
  }
});