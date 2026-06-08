const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

function checkTelegramStatus() {
    fetch('/telegram/status')
        .then(r => r.json())
        .then(data => {
            document.getElementById('telegram-loading').style.display = 'none';
            if (data.linked) {
                document.getElementById('telegram-linked').classList.add('ss-telegram-state--visible');
                document.getElementById('telegram-username').textContent = '@' + (data.username || '\u2014');
                if (data.linked_at) {
                    const d = new Date(data.linked_at);
                    document.getElementById('telegram-linked-at').textContent =
                        'Привязан ' + d.toLocaleDateString('ru-RU');
                }
            } else {
                document.getElementById('telegram-not-linked').classList.add('ss-telegram-state--visible');
            }
        })
        .catch(() => {
            document.getElementById('telegram-loading').innerHTML =
                '<span style="color: var(--ss-danger);">Ошибка загрузки</span>';
        });
}

function generateCode() {
    const btn = document.getElementById('btn-generate-code');
    btn.disabled = true;
    btn.innerHTML = '<span class="ss-spinner" style="width:16px;height:16px;border-width:2px;"></span> Генерация...';

    fetch('/telegram/generate-code', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/json',
        },
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            document.getElementById('telegram-code').textContent = data.code;
            document.getElementById('telegram-code-ttl').textContent = data.expires_in_minutes;
            document.getElementById('telegram-code-area').classList.add('ss-telegram-code--visible');
            btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg> Получить новый код';
        } else {
            alert(data.error || 'Ошибка');
        }
        btn.disabled = false;
    })
    .catch(() => {
        alert('Ошибка сети');
        btn.disabled = false;
        btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg> Получить код привязки';
    });
}

function unlinkTelegram() {
    if (!confirm('Отвязать Telegram? Уведомления перестанут приходить.')) return;

    fetch('/telegram/unlink', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            document.getElementById('telegram-linked').classList.remove('ss-telegram-state--visible');
            document.getElementById('telegram-not-linked').classList.add('ss-telegram-state--visible');
        } else {
            alert(data.error || 'Ошибка');
        }
    });
}

document.addEventListener('DOMContentLoaded', checkTelegramStatus);

// ── Form validation ──
(function () {
    const FIELD_RULES = [
        { id: 'new_words_per_day', min: 1, max: 50,  label: 'Новых слов в день' },
        { id: 'reviews_per_day',   min: 5, max: 500, label: 'Повторений в день' },
        { id: 'show_hint_time',    min: 0, max: 60,  label: 'Подсказка (сек)' },
    ];

    function clearError(fieldId) {
        const input = document.getElementById(fieldId);
        const errEl = document.getElementById('error-' + fieldId);
        if (!input || !errEl) return;
        input.classList.remove('ss-form__input--error');
        errEl.textContent = '';
        errEl.style.display = 'none';
    }

    function showError(fieldId, message) {
        const input = document.getElementById(fieldId);
        const errEl = document.getElementById('error-' + fieldId);
        if (!input || !errEl) return;
        input.classList.add('ss-form__input--error');
        errEl.textContent = message;
        errEl.style.display = 'block';
    }

    function validateField(rule) {
        const input = document.getElementById(rule.id);
        if (!input) return true;
        const raw = input.value.trim();
        if (raw === '') {
            showError(rule.id, rule.label + ': поле обязательно для заполнения');
            return false;
        }
        const val = Number(raw);
        if (!Number.isInteger(val) || isNaN(val)) {
            showError(rule.id, rule.label + ': введите целое число');
            return false;
        }
        if (val < rule.min || val > rule.max) {
            showError(rule.id, rule.label + ': допустимый диапазон ' + rule.min + '–' + rule.max);
            return false;
        }
        clearError(rule.id);
        return true;
    }

    const form = document.querySelector('form[action*="settings"]');
    if (form) {
        // Live validation on blur
        FIELD_RULES.forEach(function (rule) {
            const input = document.getElementById(rule.id);
            if (input) {
                input.addEventListener('blur', function () { validateField(rule); });
                input.addEventListener('input', function () { clearError(rule.id); });
            }
        });

        // Block submission if any field is invalid
        form.addEventListener('submit', function (e) {
            let valid = true;
            FIELD_RULES.forEach(function (rule) {
                if (!validateField(rule)) valid = false;
            });
            if (!valid) {
                e.preventDefault();
                const firstErr = form.querySelector('.ss-form__input--error');
                if (firstErr) firstErr.focus();
            }
        });
    }
})();
