(function () {
    'use strict';

    const preview = document.getElementById('landing-preview');
    if (preview) {
        const feedback = document.getElementById('preview-feedback');
        const reset = document.getElementById('preview-reset');
        const answers = preview.querySelectorAll('input[name="preview-answer"]');

        preview.addEventListener('change', function (event) {
            if (event.target.name !== 'preview-answer') return;
            const correct = event.target.value === 'am';
            feedback.textContent = (correct ? 'Правильно! ' : 'Подходит am. ')
                + 'С I используем am: I am Anna. — «Я Анна». '
                + 'Is используется с he, she, it; are — с you, we, they.';
            feedback.dataset.result = correct ? 'correct' : 'review';
            feedback.hidden = false;
            reset.hidden = false;
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
