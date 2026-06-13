document.addEventListener('DOMContentLoaded', function() {
    // Add all words
    const addAllForm = document.getElementById('add-all-form');
    const addAllBtn = document.getElementById('add-all-btn');

    if (addAllForm) {
        addAllForm.addEventListener('submit', function(e) {
            e.preventDefault();
            addAllBtn.disabled = true;
            addAllBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Добавление...';

            fetch(this.action, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams(new FormData(this))
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showToast(data.message, 'success');
                    if (data.added_count > 0) {
                        addAllBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg> Добавлено';
                        setTimeout(() => location.reload(), 2000);
                    } else {
                        addAllBtn.disabled = false;
                        addAllBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Добавить все';
                    }
                }
            })
            .catch(() => {
                addAllBtn.disabled = false;
                addAllBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg> Добавить все';
            });
        });
    }

    // Add individual word
    document.querySelectorAll('.add-word-form').forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const btn = this.querySelector('.add-word-btn');
            btn.disabled = true;
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="spin"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83"/></svg>';

            fetch(this.action, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams(new FormData(this))
            })
            .then(r => {
                if (r.ok) {
                    this.outerHTML = '<span class="cd-word__done">Изучается</span>';
                } else {
                    throw new Error();
                }
            })
            .catch(() => {
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>';
            });
        });
    });

    function showToast(msg, type) {
        const c = type === 'success' ? { bg: '#dcfce7', b: '#22c55e', i: '\u2713' } : { bg: '#dbeafe', b: '#3b82f6', i: '\u2139' };
        const t = document.createElement('div');
        t.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:9999;background:${c.bg};padding:16px 20px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.12);display:flex;align-items:center;gap:12px;border-left:4px solid ${c.b};font-family:'Onest',sans-serif;font-size:14px;font-weight:500;animation:cd-up .3s ease-out`;
        // textContent for the message — no innerHTML interpolation (audit E-103).
        const ic = document.createElement('span');
        ic.style.cssText = `color:${c.b};font-size:18px;font-weight:bold`;
        ic.textContent = c.i;
        const ms = document.createElement('span');
        ms.textContent = msg;
        t.appendChild(ic);
        t.appendChild(ms);
        document.body.appendChild(t);
        setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; setTimeout(() => t.remove(), 300); }, 3000);
    }
});
