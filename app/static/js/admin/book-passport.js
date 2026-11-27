(() => {
    const passport = document.querySelector('[data-book-passport]');
    if (!passport) return;

    const form = passport.closest('form');
    const token = form.elements.passport_token;
    const revision = form.elements.passport_revision;
    const sourceFile = form.elements.file;
    const summary = passport.querySelector('[data-passport-summary]');
    const status = passport.querySelector('[data-passport-status]');
    const preview = passport.querySelector('[data-passport-preview]');
    const current = passport.querySelector('[data-passport-current]');
    const fields = ['source_edition_id', 'source_format', 'source_url', 'permission_document'];
    const initial = fields.map(name => form.elements[name]?.value);
    let generation = 0;
    let previewed = Boolean(passport.querySelector('[role="alert"]'));

    function invalidate() {
        generation += 1;
        token.value = '';
        summary.hidden = true;
        if (previewed) status.textContent = 'Проверьте паспорт перед сохранением.';
    }

    form.addEventListener('input', invalidate);
    form.addEventListener('change', invalidate);
    form.addEventListener('submit', event => {
        const changed = fields.some((name, index) => form.elements[name]?.value !== initial[index]);
        if (!token.value && (previewed || changed)) {
            event.preventDefault();
            status.textContent = 'Сначала откройте предпросмотр паспорта.';
            preview.focus();
        }
    });

    preview.addEventListener('click', async () => {
        const version = generation;
        const body = new FormData(form);
        body.delete('cover_image');
        preview.disabled = true;
        status.textContent = 'Готовим предпросмотр…';
        try {
            const response = await fetch(passport.dataset.previewUrl, {
                method: 'POST',
                headers: {Accept: 'application/json'},
                body,
            });
            const data = await response.json();
            if (version !== generation) return;
            if (!response.ok) {
                if (response.status === 409 && typeof data.revision === 'string') {
                    revision.value = data.revision;
                    if (current) current.hidden = false;
                }
                invalidate();
                status.textContent = data.error || 'Не удалось подготовить предпросмотр.';
                return;
            }
            for (const field of fields) {
                let value = data.values[field];
                if (field === 'source_format' && value) value = value === 'text' ? 'Вставленный текст' : value.toUpperCase();
                summary.querySelector(`[data-preview-value="${field}"]`).textContent = value || 'Не указано';
            }
            previewed = true;
            token.value = data.token;
            summary.hidden = false;
            status.textContent = 'Сверьте сведения и сохраните форму.';
            summary.querySelector('h6').focus();
        } catch {
            if (version === generation) status.textContent = 'Не удалось подготовить предпросмотр. Повторите попытку.';
        } finally {
            preview.disabled = false;
        }
    });

    if (!sourceFile) return;
    const suggestions = passport.querySelector('[data-passport-suggestions]');
    const use = suggestions.querySelector('[data-passport-use]');
    let metadata = {};
    sourceFile.addEventListener('change', () => {
        metadata = {};
        suggestions.hidden = true;
    });
    form.addEventListener('book:source-metadata', event => {
        if (event.detail.source_format !== 'epub') return;
        metadata = event.detail;
        invalidate();
        for (const node of suggestions.querySelectorAll('[data-suggestion]')) {
            node.textContent = metadata[node.dataset.suggestion] || 'Не указано';
        }
        use.hidden = !metadata.source_edition_id && !metadata.source_url;
        suggestions.hidden = false;
    });
    use.addEventListener('click', () => {
        for (const field of ['source_edition_id', 'source_url']) {
            if (!form.elements[field].value && metadata[field]) {
                form.elements[field].value = metadata[field].slice(0, form.elements[field].maxLength);
            }
        }
        invalidate();
        form.elements.source_edition_id.focus();
    });
})();
