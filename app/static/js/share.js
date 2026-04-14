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

        case 'whatsapp':
            window.open(
                'https://wa.me/?text=' + encodeURIComponent((text ? text + ' ' : '') + url),
                '_blank',
                'width=600,height=400'
            );
            break;

        case 'twitter':
            window.open(
                'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(url),
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
                // Clipboard API may fail if page lacks focus or HTTPS — fallback to execCommand
                try {
                    var ta = document.createElement('textarea');
                    ta.value = fullText;
                    ta.style.position = 'fixed';
                    ta.style.left = '-9999px';
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                } catch (_) {
                    // Copy completely unsupported
                }
            });
            break;

        default:
            // Fallback to Web Share API if available
            if (navigator.share) {
                navigator.share({ title: text, url: url });
            }
    }
}

document.addEventListener('click', function(event) {
    var button = event.target.closest('.share-btn[data-platform]');
    if (!button) {
        return;
    }

    shareVia(
        button.dataset.platform || '',
        button.dataset.shareText || '',
        button.dataset.shareUrl || window.location.href
    );
});
