(function() {
    var form = document.getElementById('user-reply-form');
    if (!form) return;
    var submit = document.getElementById('user-reply-submit');
    var errorBox = document.getElementById('user-reply-error');
    var body = document.getElementById('user-reply-body');
    var inFlight = false;

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        if (inFlight) return;
        var text = (body.value || '').trim();
        if (!text) {
            errorBox.textContent = 'Опишите свой ответ.';
            errorBox.hidden = false;
            return;
        }
        errorBox.hidden = true;
        inFlight = true;
        submit.disabled = true;
        var metaTag = document.querySelector('meta[name="csrf-token"]');
        var csrf = metaTag ? metaTag.getAttribute('content') : '';
        fetch(window.FEEDBACK_REPLY_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf,
                'Accept': 'application/json',
            },
            body: JSON.stringify({body: text}),
        }).then(function(r) {
            if (r.ok) {
                window.location.reload();
                return;
            }
            return r.json().catch(function() { return {}; }).then(function(j) {
                errorBox.textContent = (j && j.message) ? j.message : 'Не удалось отправить ответ.';
                errorBox.hidden = false;
                inFlight = false;
                submit.disabled = false;
            });
        }).catch(function() {
            errorBox.textContent = 'Сеть недоступна.';
            errorBox.hidden = false;
            inFlight = false;
            submit.disabled = false;
        });
    });
})();
