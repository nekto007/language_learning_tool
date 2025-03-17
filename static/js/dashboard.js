/**
 * Dashboard Page JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
  initCardAnimations();
  initBookSearch();
  initActivityRefresh();
});

/**
 * Initialize hover and animation effects for dashboard cards
 */
function initCardAnimations() {
  // Add subtle animations to stat cards and other elements
  document.querySelectorAll('.stat-card, .quick-action-item').forEach(card => {
    card.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-5px)';
      this.style.boxShadow = 'var(--shadow-lg)';
    });

    card.addEventListener('mouseleave', function() {
      this.style.transform = '';
      this.style.boxShadow = '';
    });
  });

  // Add a staggered fade-in animation for dashboard elements
  const elements = [
    ...document.querySelectorAll('.stat-card'),
    ...document.querySelectorAll('.dashboard-card'),
    ...document.querySelectorAll('.quick-action-item'),
    ...document.querySelectorAll('.book-item'),
    ...document.querySelectorAll('.activity-item')
  ];

  elements.forEach((element, index) => {
    // Set initial state (invisible)
    element.style.opacity = '0';
    element.style.transform = 'translateY(20px)';
    element.style.transition = 'opacity 0.5s ease, transform 0.5s ease';

    // Animate in with a staggered delay
    setTimeout(() => {
      element.style.opacity = '1';
      element.style.transform = 'translateY(0)';
    }, 100 + (index * 50)); // Staggered delay
  });
}

/**
 * Initialize search functionality for book items
 */
function initBookSearch() {
  // This could be expanded to add a quick search for books
  const booksList = document.querySelector('.books-list');
  const books = document.querySelectorAll('.book-item');

  if (!booksList || !books.length) return;

  // Create search input element
  const searchContainer = document.createElement('div');
  searchContainer.className = 'book-search-container';
  searchContainer.innerHTML = `
    <div class="input-group mb-3">
      <span class="input-group-text">
        <i class="bi bi-search"></i>
      </span>
      <input type="text" class="form-control" id="bookSearch" placeholder="Search books...">
    </div>
  `;

  // Insert before the books list
  booksList.parentNode.insertBefore(searchContainer, booksList);

  // Add search functionality
  const searchInput = document.getElementById('bookSearch');
  if (searchInput) {
    searchInput.addEventListener('input', debounce(function() {
      const searchTerm = this.value.toLowerCase().trim();

      if (searchTerm === '') {
        // Show all books if search is empty
        books.forEach(book => {
          book.style.display = '';
        });
        return;
      }

      // Filter books based on search term
      books.forEach(book => {
        const title = book.querySelector('.book-title').textContent.toLowerCase();
        if (title.includes(searchTerm)) {
          book.style.display = '';
        } else {
          book.style.display = 'none';
        }
      });
    }, 300));
  }
}

/**
 * Initialize automated refresh for activity feed
 */
function initActivityRefresh() {
  const activityList = document.querySelector('.activity-list');
  if (!activityList) return;

  // In a real implementation, you would fetch new activities from the server
  // For this demo, we'll simulate it with some sample activities
  const sampleActivities = [
    {
      title: 'Added new word: "exemplary"',
      time: '2 minutes ago',
      icon: 'bi-plus-circle',
      bgClass: 'bg-secondary'
    },
    {
      title: 'Moved 3 words to active learning',
      time: '15 minutes ago',
      icon: 'bi-arrow-right',
      bgClass: 'bg-primary'
    },
    {
      title: 'Completed daily learning goal',
      time: '1 hour ago',
      icon: 'bi-check-circle',
      bgClass: 'bg-success'
    }
  ];

  // Function to fetch and update activity feed
  function updateActivityFeed() {
    // In a real implementation, this would be an API call
    // For demo, we'll just rotate through sample activities

    // Get first activity and remove it
    const firstActivity = activityList.querySelector('.activity-item');
    if (firstActivity) {
      // Animate removal
      firstActivity.style.opacity = '0';
      firstActivity.style.height = `${firstActivity.offsetHeight}px`;
      firstActivity.style.transform = 'translateX(-20px)';
      firstActivity.style.overflow = 'hidden';

      setTimeout(() => {
        firstActivity.remove();

        // Get random new activity
        const newActivity = sampleActivities[Math.floor(Math.random() * sampleActivities.length)];

        // Create new activity element
        const activityItem = document.createElement('div');
        activityItem.className = 'activity-item';
        activityItem.style.opacity = '0';
        activityItem.style.transform = 'translateX(20px)';
        activityItem.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        activityItem.innerHTML = `
          <div class="activity-icon ${newActivity.bgClass}">
            <i class="bi ${newActivity.icon}"></i>
          </div>
          <div class="activity-content">
            <div class="activity-title">${newActivity.title}</div>
            <div class="activity-time">${newActivity.time}</div>
          </div>
        `;

        // Add to list
        activityList.appendChild(activityItem);

        // Trigger animation
        setTimeout(() => {
          activityItem.style.opacity = '1';
          activityItem.style.transform = 'translateX(0)';
        }, 50);
      }, 500);
    }
  }

  // Update activity feed every 60 seconds
  //setInterval(updateActivityFeed, 60000);

  // You could also add a manual refresh button
  const refreshButton = document.querySelector('.card-header .btn-icon[data-bs-toggle="dropdown"]');
  if (refreshButton) {
    // Clone the button and replace it with a refresh button
    const refreshButtonNew = document.createElement('button');
    refreshButtonNew.className = 'btn btn-sm btn-icon';
    refreshButtonNew.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
    refreshButtonNew.title = 'Refresh activities';

    refreshButtonNew.addEventListener('click', function() {
      // Add spinner while refreshing
      this.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i>';
      this.disabled = true;

      // Update after a delay to simulate loading
      setTimeout(() => {
        updateActivityFeed();

        // Restore button
        this.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
        this.disabled = false;
      }, 1000);
    });

    // Add the spinner animation style
    const style = document.createElement('style');
    style.textContent = `
      .spin {
        animation: spin 1s linear infinite;
      }
      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
    `;
    document.head.appendChild(style);

    // Replace the dropdown with the refresh button
    refreshButton.parentNode.replaceChild(refreshButtonNew, refreshButton);
  }
}

/**
 * Add interactions for the books list
 */
function initBookInteractions() {
  const bookItems = document.querySelectorAll('.book-item');

  bookItems.forEach(item => {
    item.addEventListener('mouseenter', function() {
      // Add hover effect
      this.style.backgroundColor = 'rgba(var(--primary-color-rgb), 0.05)';
    });

    item.addEventListener('mouseleave', function() {
      // Remove hover effect
      this.style.backgroundColor = '';
    });

    // Make the entire item clickable
    item.addEventListener('click', function(e) {
      // Don't trigger if clicking on a button or link
      if (e.target.closest('.btn') || e.target.closest('a')) {
        return;
      }

      // Get the view words link and navigate to it
      const viewLink = this.querySelector('.book-actions a');
      if (viewLink) {
        window.location.href = viewLink.getAttribute('href');
      }
    });
  });
}