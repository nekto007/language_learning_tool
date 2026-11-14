(function () {
    'use strict';

    const preview = document.getElementById('landing-preview');
    if (preview) {
        const feedback = document.getElementById('preview-feedback');
        const reset = document.getElementById('preview-reset');
        const answers = preview.querySelectorAll('input[name="preview-answer"]');
        const sent = new Set((preview.dataset.recordedEvents || '').split(',').filter(Boolean));
        const gaNames = {
            preview_started: 'landing_preview_started',
            preview_answered: 'landing_preview_answered',
            registration_clicked: 'landing_registration_click'
        };

        function emit(event, correct) {
            if (sent.has(event)) return;
            sent.add(event);
            const payload = {event: event, preview_id: preview.dataset.previewId};
            if (event === 'preview_answered') payload.correct = correct;
            if (typeof window.gtag === 'function') {
                try {
                    const params = {preview_id: payload.preview_id, level: 'A1'};
                    if (event === 'preview_answered') params.correct = correct;
                    window.gtag('event', gaNames[event], params);
                } catch (_) { /* Analytics must not interrupt the example. */ }
            }
            const csrf = document.querySelector('meta[name="csrf-token"]');
            if (preview.dataset.eventUrl && csrf && typeof fetch === 'function') {
                try {
                    fetch(preview.dataset.eventUrl, {
                        method: 'POST', credentials: 'same-origin', keepalive: true,
                        headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrf.content},
                        body: JSON.stringify(payload)
                    }).catch(function () {});
                } catch (_) { /* Navigation and practice keep working offline. */ }
            }
        }

        preview.addEventListener('focusin', function (event) {
            if (event.target.name === 'preview-answer') emit('preview_started');
        });
        const registration = document.getElementById('preview-register');
        if (registration) registration.addEventListener('click', function () { emit('registration_clicked'); });

        preview.addEventListener('change', function (event) {
            if (event.target.name !== 'preview-answer') return;
            const correct = event.target.value === preview.dataset.correct;
            feedback.textContent = (correct ? 'Правильно! ' : 'Подходит «' + preview.dataset.correct + '». ')
                + preview.dataset.explanation;
            feedback.dataset.result = correct ? 'correct' : 'review';
            feedback.hidden = false;
            reset.hidden = false;
            emit('preview_started');
            emit('preview_answered', correct);
        });

        reset.addEventListener('click', function () {
            answers.forEach(function (answer) { answer.checked = false; });
            feedback.hidden = true;
            feedback.textContent = '';
            delete feedback.dataset.result;
            reset.hidden = true;
            answers[0].focus();
        });
    }

    const copy = document.getElementById('landing-share-copy');
    if (copy) {
        copy.addEventListener('click', async function () {
            const link = document.getElementById('landing-share-url');
            const status = document.getElementById('landing-share-status');
            try {
                await navigator.clipboard.writeText(link.value);
                status.textContent = 'Ссылка скопирована. Её можно отправить другу.';
            } catch (_) {
                link.focus();
                link.select();
                status.textContent = 'Скопируйте выделенную ссылку через меню браузера или сочетанием Ctrl+C (⌘C на Mac).';
            }
        });
    }
}());
