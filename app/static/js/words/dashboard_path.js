// Click-on-locked-node → toast.
(function() {
  var shell = document.querySelector('.path-shell');
  if (!shell) return;
  var msg = shell.getAttribute('data-toast-locked') || 'Сначала завершите предыдущее задание';
  shell.addEventListener('click', function(e) {
    var locked = e.target.closest('.path-node--locked');
    if (!locked) return;
    e.preventDefault();
    var existing = document.getElementById('path-toast');
    if (existing) existing.parentNode.removeChild(existing);
    var t = document.createElement('div');
    t.id = 'path-toast';
    t.className = 'path-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function() { t.classList.add('path-toast--visible'); });
    setTimeout(function() {
      t.classList.remove('path-toast--visible');
      setTimeout(function() { t.parentNode && t.parentNode.removeChild(t); }, 250);
    }, 1800);
  });
})();
