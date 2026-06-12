function copyReferralLink() {
    const url = document.getElementById('referral-url').textContent.trim();
    const btn = document.querySelector('.ref-link-card__btn');
    const showResult = function(ok) {
        if (!btn) return;
        btn.textContent = ok ? 'Скопировано!' : 'Не удалось скопировать';
        setTimeout(function() { btn.textContent = 'Копировать'; }, 2000);
    };
    if (typeof lltCopyText === 'function') {
        lltCopyText(url, showResult);
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(
            function() { showResult(true); },
            function() { showResult(false); }
        );
    } else {
        try { window.prompt('Скопируйте ссылку:', url); } catch (e) {}
    }
}
