/**
 * Share functionality with Web Share API fallback.
 */
function shareVia(platform, text, url) {
    switch (platform) {
        case 'telegram':
            window.open(
                'https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(text),
                '_blank',
                'width=600,height=400'
            );
            break;

        case 'linkedin':
            window.open(
                'https://www.linkedin.com/sharing/share-offsite/?url=' + encodeURIComponent(url),
                '_blank',
                'width=600,height=400'
            );
            break;

        case 'copy':
            var fullText = text ? text + ' ' + url : url;
            navigator.clipboard.writeText(fullText).then(function() {
                // Find the button that was clicked and show feedback
                var btns = document.querySelectorAll('.share-btn--copy');
                btns.forEach(function(btn) {
                    btn.classList.add('share-btn--copied');
                    var label = btn.querySelector('.share-btn__label');
                    if (label) {
                        var orig = label.textContent;
                        label.textContent = 'Скопировано!';
                        setTimeout(function() {
                            btn.classList.remove('share-btn--copied');
                            label.textContent = orig;
                        }, 2000);
                    } else {
                        setTimeout(function() {
                            btn.classList.remove('share-btn--copied');
                        }, 2000);
                    }
                });
            }).catch(function() {
                // Clipboard API may fail if page lacks focus or HTTPS
            });
            break;

        default:
            // Fallback to Web Share API if available
            if (navigator.share) {
                navigator.share({ title: text, url: url });
            }
    }
}
