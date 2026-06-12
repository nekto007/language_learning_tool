/**
 * Share functionality with Web Share API fallback.
 */

/**
 * Copy text to clipboard with execCommand fallback.
 * onDone(success: boolean) is called in both paths.
 */
function lltCopyText(text, onDone) {
    var done = typeof onDone === 'function' ? onDone : function () {};
    var fallbackCopy = function () {
        try {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            var ok = document.execCommand('copy');
            document.body.removeChild(ta);
            done(ok);
        } catch (_) {
            done(false);
        }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
            done(true);
        }).catch(function () {
            // Clipboard API may fail if page lacks focus or HTTPS
            fallbackCopy();
        });
    } else {
        fallbackCopy();
    }
}

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
            // share-offsite игнорирует текст — feed-композер преднабирает пост целиком
            window.open(
                'https://www.linkedin.com/feed/?shareActive=true&text=' + encodeURIComponent((text ? text + ' ' : '') + url),
                '_blank',
                'width=900,height=650'
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
            lltCopyText(fullText, function (ok) {
                if (!ok) return;
                var btns = document.querySelectorAll('.share-btn--copy');
                btns.forEach(function (btn) {
                    btn.classList.add('share-btn--copied');
                    var label = btn.querySelector('.share-btn__label');
                    if (label) {
                        var orig = label.textContent;
                        label.textContent = 'Скопировано!';
                        setTimeout(function () {
                            btn.classList.remove('share-btn--copied');
                            label.textContent = orig;
                        }, 2000);
                    } else {
                        setTimeout(function () {
                            btn.classList.remove('share-btn--copied');
                        }, 2000);
                    }
                });
            });
            break;

        default:
            // Fallback to Web Share API if available
            if (navigator.share) {
                navigator.share({ title: text, url: url }).catch(function () {});
            }
    }
}

// Guard: share.js может быть подключён дважды (base + page block) —
// без него каждый клик открывал бы два popup-окна.
if (!window.__lltShareBound) {
    window.__lltShareBound = true;
    document.addEventListener('click', function (event) {
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
}
