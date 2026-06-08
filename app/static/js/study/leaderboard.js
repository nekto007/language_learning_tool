document.addEventListener('DOMContentLoaded', function() {
  const tabs = document.querySelectorAll('.lb-tabs__btn');
  const panels = document.querySelectorAll('.lb-panel');

  tabs.forEach(function(tab) {
    tab.addEventListener('click', function() {
      var target = this.getAttribute('data-tab');

      tabs.forEach(function(t) { t.classList.remove('lb-tabs__btn--active'); });
      panels.forEach(function(p) { p.classList.remove('lb-panel--active'); });

      this.classList.add('lb-tabs__btn--active');
      document.querySelector('.lb-panel[data-panel="' + target + '"]').classList.add('lb-panel--active');
    });
  });
});
