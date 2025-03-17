/**
 * Homepage JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
  initScrollAnimation();
  initMobileMenuEnhancements();
});

/**
 * Initialize scroll animations
 */
function initScrollAnimation() {
  const animatedElements = document.querySelectorAll('.feature-card, .step-item');

  // Intersection Observer for revealing elements on scroll
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('animated');
        // Unobserve after animation to save resources
        observer.unobserve(entry.target);
      }
    });
  }, {
    root: null, // viewport
    threshold: 0.15, // 15% of the item visible
    rootMargin: '0px 0px -10% 0px' // trigger a bit before the item is visible
  });

  // Observe each element
  animatedElements.forEach(element => {
    // Add the initial hidden class
    element.classList.add('animate-on-scroll');
    observer.observe(element);
  });

  // Smooth scrolling for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const href = this.getAttribute('href');

      if (href !== '#') {
        e.preventDefault();

        const targetElement = document.querySelector(href);
        if (targetElement) {
          window.scrollTo({
            top: targetElement.offsetTop - 80, // Offset for fixed header
            behavior: 'smooth'
          });
        }
      }
    });
  });
}

/**
 * Initialize mobile menu enhancements
 */
function initMobileMenuEnhancements() {
  // Close mobile menu when clicking outside
  document.addEventListener('click', function(e) {
    const navbarCollapse = document.querySelector('.navbar-collapse.show');

    if (navbarCollapse && !navbarCollapse.contains(e.target) &&
        !e.target.classList.contains('navbar-toggler')) {
      // Find the toggler button and click it to close the menu
      document.querySelector('.navbar-toggler').click();
    }
  });

  // Close mobile menu when a nav link is clicked
  const navLinks = document.querySelectorAll('.navbar-nav .nav-link');
  const navbarToggler = document.querySelector('.navbar-toggler');

  navLinks.forEach(link => {
    link.addEventListener('click', function() {
      if (window.innerWidth < 992 && document.querySelector('.navbar-collapse.show')) {
        navbarToggler.click();
      }
    });
  });
}

/**
 * CSS for animations in JavaScript to avoid separate CSS file for just a few lines
 */
(function() {
  const style = document.createElement('style');
  style.textContent = `
    .animate-on-scroll {
      opacity: 0;
      transform: translateY(30px);
      transition: opacity 0.6s ease, transform 0.6s ease;
    }
    
    .animate-on-scroll.animated {
      opacity: 1;
      transform: translateY(0);
    }
    
    .feature-card:nth-child(2) {
      transition-delay: 0.1s;
    }
    
    .feature-card:nth-child(3) {
      transition-delay: 0.2s;
    }
    
    .step-item:nth-child(2) {
      transition-delay: 0.1s;
    }
    
    .step-item:nth-child(3) {
      transition-delay: 0.2s;
    }
    
    .step-item:nth-child(4) {
      transition-delay: 0.3s;
    }
  `;
  document.head.appendChild(style);
})();