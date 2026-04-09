/**
 * Share functionality for LLT English.
 * Used by components/share_buttons.html
 */

function shareVia(platform, url, text) {
    const encodedUrl = encodeURIComponent(url);
    const encodedText = encodeURIComponent(text);
    let shareUrl;

    switch (platform) {
        case 'telegram':
            shareUrl = `https://t.me/share/url?url=${encodedUrl}&text=${encodedText}`;
            break;
        case 'whatsapp':
            shareUrl = `https://wa.me/?text=${encodedText}%20${encodedUrl}`;
            break;
        case 'twitter':
            shareUrl = `https://twitter.com/intent/tweet?url=${encodedUrl}&text=${encodedText}`;
            break;
        default:
            return;
    }

    window.open(shareUrl, '_blank', 'width=600,height=400,noopener,noreferrer');
}

function copyShareLink(url) {
    navigator.clipboard.writeText(url).then(function() {
        // Find the button that was clicked and update its label
        const btns = document.querySelectorAll('.share-btn--copy .share-btn__copy-label');
        btns.forEach(function(label) {
            const original = label.textContent;
            label.textContent = 'Скопировано!';
            setTimeout(function() { label.textContent = original; }, 2000);
        });
    }).catch(function() {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = url;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    });
}
