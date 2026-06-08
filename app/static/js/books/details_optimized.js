// Animate stats on scroll
const observerOptions = {
    threshold: 0.5,
    rootMargin: '0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const statValues = entry.target.querySelectorAll('.stat-value');
            statValues.forEach(stat => {
                const finalValue = parseInt(stat.textContent);
                let currentValue = 0;
                const increment = Math.ceil(finalValue / 20);
                
                const counter = setInterval(() => {
                    currentValue += increment;
                    if (currentValue >= finalValue) {
                        currentValue = finalValue;
                        clearInterval(counter);
                    }
                    stat.textContent = currentValue;
                }, 50);
            });
            observer.unobserve(entry.target);
        }
    });
}, observerOptions);

// Observe stats section
const statsSection = document.querySelector('.progress-section');
if (statsSection) {
    observer.observe(statsSection);
}

// Initialize tooltips
var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
});

// Initialize Bootstrap tabs
document.addEventListener('DOMContentLoaded', function() {
    // Initialize all tabs
    var triggerTabList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tab"]'));
    triggerTabList.forEach(function (triggerEl) {
        triggerEl.addEventListener('click', function (event) {
            event.preventDefault();
            var tab = new bootstrap.Tab(triggerEl);
            tab.show();
        });
    });
});

// Propagate ?from=daily_plan to chapter reader links
(function() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('from') !== 'daily_plan') return;
    document.querySelectorAll('.chapter-item a[href]').forEach(function(link) {
        var sep = link.href.indexOf('?') === -1 ? '?' : '&';
        link.href += sep + 'from=daily_plan';
    });
})();
