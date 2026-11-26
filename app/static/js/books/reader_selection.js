(() => {
    'use strict';

    const reader = document.getElementById('readerBody');
    const chapter = document.getElementById('chapterContent');
    const trigger = document.getElementById('reader-phrase-trigger');
    const dialog = document.getElementById('readerPhrase');
    const status = document.getElementById('reader-phrase-status');
    const translation = document.getElementById('reader-phrase-translation');
    const fields = document.getElementById('reader-phrase-fields');
    const result = document.getElementById('reader-phrase-result');
    const review = document.getElementById('reader-phrase-review');
    const form = dialog.querySelector('form');
    const submit = form.querySelector('button[type=submit]');

    let candidate;
    let pressed;
    let opened;
    let operation = 0;
    let returnFocus;

    function paragraphFor(node) {
        const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
        const paragraph = element?.closest('p');
        return paragraph?.parentElement === chapter ? paragraph : null;
    }

    function charOffset(paragraph, node, offset) {
        const prefix = document.createRange();
        prefix.selectNodeContents(paragraph);
        prefix.setEnd(node, offset);
        return [...prefix.toString()].length;
    }

    function updateSelection() {
        if (pressed || dialog.open) return;
        candidate = null;
        const selection = window.getSelection();
        if (selection?.rangeCount === 1 && !selection.isCollapsed) {
            const range = selection.getRangeAt(0);
            const paragraph = paragraphFor(range.startContainer);
            if (paragraph && paragraph === paragraphFor(range.endContainer)) {
                const selected = [...range.toString().trim()];
                if (selected.length <= 200 && /[A-Za-z]/.test(selected.join(''))) {
                    candidate = {
                        paragraph: Array.prototype.indexOf.call(chapter.children, paragraph),
                        start: charOffset(paragraph, range.startContainer, range.startOffset),
                        end: charOffset(paragraph, range.endContainer, range.endOffset),
                        revision: reader.dataset.revision,
                    };
                }
            }
        }
        trigger.hidden = !candidate;
    }

    async function request(data) {
        const response = await fetch(dialog.dataset.endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
            },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            const message = response.status === 409
                ? 'Текст главы изменился. Обнови страницу и выдели фразу снова.'
                : 'Не удалось получить данные. Попробуй ещё раз.';
            throw new Error(message);
        }
        return response.json();
    }

    document.addEventListener('selectionchange', updateSelection);
    trigger.addEventListener('pointerdown', event => {
        pressed = candidate;
        if (event.pointerType === 'mouse') event.preventDefault();
    });
    trigger.addEventListener('pointercancel', () => {
        pressed = null;
        updateSelection();
    });
    trigger.addEventListener('click', async () => {
        opened = pressed ?? candidate;
        pressed = null;
        if (!opened) return;
        returnFocus = document.activeElement;
        const ticket = ++operation;
        result.hidden = fields.hidden = true;
        trigger.hidden = true;
        dialog.showModal();
        status.textContent = 'Открываем фразу…';
        try {
            const data = await request(opened);
            if (ticket !== operation) return;
            document.getElementById('reader-phrase-text').textContent = data.english;
            document.getElementById('reader-phrase-context').textContent = data.context;
            translation.value = data.translation;
            translation.placeholder = data.translation ? '' : 'Введи свой вариант';
            status.textContent = '';
            fields.hidden = false;
            translation.focus();
            if (data.translation) translation.select();
        } catch (error) {
            if (ticket === operation) status.textContent = error.message;
        }
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const value = translation.value.trim();
        if (!value || !opened || submit.disabled) return;
        submit.disabled = true;
        const ticket = operation;
        status.textContent = 'Сохраняем…';
        try {
            const data = await request({
                ...opened, translation: value, back: dialog.dataset.back, plan: dialog.dataset.plan === 'true',
            });
            if (ticket !== operation) return;
            fields.hidden = true;
            result.hidden = false;
            status.textContent = 'Фраза сохранена в «Словах из книг».';
            review.hidden = !data.review_url;
            if (data.review_url) review.href = data.review_url;
            const collection = document.getElementById('reader-phrase-collection');
            collection.href = data.collection_url;
            (data.review_url ? review : collection).focus();
        } catch (error) {
            if (ticket === operation) status.textContent = error.message;
        } finally {
            submit.disabled = false;
        }
    });
    dialog.querySelector('[data-phrase-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
        operation++;
        opened = null;
        updateSelection();
        const focus = returnFocus && returnFocus !== trigger && reader.contains(returnFocus) ? returnFocus : reader;
        focus.focus({preventScroll: true});
    });
})();
