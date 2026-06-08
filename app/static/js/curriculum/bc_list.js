function filterCourses() {
  const level = document.getElementById('filter-level').value;
  const status = document.getElementById('filter-status').value;

  document.querySelectorAll('.bc-card-link').forEach(card => {
    const cardLevel = card.dataset.level;
    const cardEnrolled = card.dataset.enrolled;

    let show = true;
    if (level && cardLevel !== level) show = false;
    if (status === 'enrolled' && cardEnrolled !== 'true') show = false;
    if (status === 'available' && cardEnrolled === 'true') show = false;

    card.style.display = show ? '' : 'none';
  });

  // Hide empty sections
  document.querySelectorAll('.bc-section').forEach(section => {
    const cards = section.querySelectorAll('.bc-card-link:not([style*="display: none"])');
    const isFilterSection = section.classList.contains('bc-filter-section');
    if (!isFilterSection) {
      section.style.display = cards.length > 0 ? '' : 'none';
    }
  });
}
