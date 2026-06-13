document.addEventListener('DOMContentLoaded', function() {
    const addCollectionForms = document.querySelectorAll('.add-collection-form');

    addCollectionForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();

            const submitBtn = this.querySelector('.add-collection-btn');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>';

            fetch(this.action, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams(new FormData(this))
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showCollToast(data.message, 'success');

                    if (data.added_count > 0) {
                        submitBtn.style.background = '#22c55e';
                        submitBtn.style.borderColor = '#22c55e';
                        submitBtn.style.color = 'white';
                        submitBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>';
                        submitBtn.disabled = true;

                        setTimeout(() => location.reload(), 2000);
                    } else {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>';
                    }
                }
            })
            .catch(error => {
                console.error('Error:', error);
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>';
            });
        });
    });

    function showCollToast(message, type) {
        const colors = {
            success: { bg: '#dcfce7', border: '#22c55e', icon: '\u2713' },
            info: { bg: '#dbeafe', border: '#3b82f6', icon: '\u2139' }
        };
        const c = colors[type] || colors.info;

        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; bottom: 24px; right: 24px; z-index: 9999;
            background: ${c.bg}; padding: 16px 20px; border-radius: 12px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.12); display: flex; align-items: center; gap: 12px;
            border-left: 4px solid ${c.border}; font-family: 'Onest', sans-serif; font-size: 14px; font-weight: 500;
            animation: coll-slideUp 0.3s ease-out;
        `;
        // NOTE (audit E-099): the slideUp CSS keyframe is neutralized by the
        // global @media (prefers-reduced-motion: reduce) rule. If this is ever
        // moved to JS / Web Animations, add an explicit matchMedia guard here.
        // textContent, not innerHTML, for the server-supplied message — avoids
        // DOM-XSS if a message ever reflects user input (audit E-095).
        const iconSpan = document.createElement('span');
        iconSpan.style.cssText = `color: ${c.border}; font-size: 18px; font-weight: bold;`;
        iconSpan.textContent = c.icon;
        const msgSpan = document.createElement('span');
        msgSpan.textContent = message;
        toast.appendChild(iconSpan);
        toast.appendChild(msgSpan);
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
});
