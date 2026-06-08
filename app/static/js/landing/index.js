document.addEventListener('click', function(e) {
    var btn = e.target.closest('.land-audio-btn');
    if (!btn) return;
    var a = document.getElementById('audioPlayer');
    if (!a) return;
    a.src = btn.getAttribute('data-audio-url') || '';
    a.play().catch(function() {
        if (btn.dataset.audioErrShown) return;
        var msg = document.createElement('span');
        msg.textContent = ' Аудио недоступно';
        msg.style.color = 'var(--land-text-muted)';
        msg.style.fontSize = '0.8rem';
        btn.parentNode.insertBefore(msg, btn.nextSibling);
        btn.dataset.audioErrShown = '1';
    });
});
