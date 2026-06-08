function copyReferralLink() {
    const url = document.getElementById('referral-url').textContent;
    navigator.clipboard.writeText(url).then(function() {
        const btn = document.querySelector('.ref-link-card__btn');
        btn.textContent = 'Скопировано!';
        setTimeout(function() { btn.textContent = 'Копировать'; }, 2000);
    });
}
