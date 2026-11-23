/* Formative practice. The same hints/model answers are served to native apps. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root && root.document) api.mount(root.document);
})(typeof window === 'undefined' ? null : window, function () {
    'use strict';
    class Practice {
        constructor(questions) {
            if (!Array.isArray(questions) || questions.length < 2 || questions.length > 3 ||
                new Set(questions.map(q => q.id)).size !== questions.length ||
                questions.some(q => !q.id || !q.explanation || !Array.isArray(q.options) ||
                    q.options.length !== 3 || new Set(q.options.map(o => o.id)).size !== 3 ||
                    !q.options.some(o => o.id === q.correct_option))) throw new Error('Invalid reading practice');
            this.questions = questions;
            this.restart();
        }
        restart() { this.index = 0; this.selection = null; this.feedback = null; this.completed = false; this.answers = []; }
        snapshot() {
            return {version: 1, index: this.index, selection: this.selection,
                checked: Boolean(this.feedback), completed: this.completed, answers: [...this.answers]};
        }
        restore(value) {
            if (!value || value.version !== 1 || !Number.isInteger(value.index) ||
                value.index < 0 || value.index >= this.questions.length ||
                typeof value.checked !== 'boolean' || typeof value.completed !== 'boolean' ||
                !Array.isArray(value.answers) || value.answers.length > this.questions.length ||
                value.answers.some((id, index) => id !== this.questions[index].correct_option) ||
                !(value.selection === null || typeof value.selection === 'string')) return false;
            const complete = value.answers.length === this.questions.length;
            if (complete !== value.completed || (complete && (value.index !== this.questions.length - 1 || value.selection !== null || value.checked)) ||
                (!complete && value.answers.length !== value.index)) return false;
            const question = this.questions[value.index];
            if ((value.selection !== null && !question.options.some(option => option.id === value.selection)) ||
                (value.checked && value.selection === null)) return false;
            this.index = value.index; this.answers = [...value.answers]; this.selection = value.selection;
            this.completed = complete;
            // Never restore a stored verdict/explanation. Only current content grades input.
            this.feedback = value.checked ? {correct: value.selection === question.correct_option, explanation: question.explanation} : null;
            return true;
        }
        get question() { return this.completed ? null : this.questions[this.index]; }
        choose(id) {
            if (!this.feedback && this.question && this.question.options.some(o => o.id === id)) this.selection = id;
        }
        check() {
            if (!this.selection || this.feedback || !this.question) return;
            this.feedback = {correct: this.selection === this.question.correct_option, explanation: this.question.explanation};
        }
        continue() {
            if (!this.feedback) return;
            if (this.feedback.correct) {
                this.answers.push(this.selection);
                if (this.index + 1 === this.questions.length) this.completed = true;
                else this.index += 1;
            }
            this.selection = null;
            this.feedback = null;
        }
    }
    async function contentDigest(value) {
        const bytes = new TextEncoder().encode(JSON.stringify(value));
        const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
        return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    }
    class DraftStore {
        constructor(storage, identity, revision) {
            if (!identity || !['account', 'book', 'chapter'].every(key => /^[1-9][0-9]*$/.test(String(identity[key]))) ||
                !/^[a-f0-9]{64}$/.test(revision)) throw new Error('Invalid reading draft identity');
            this.storage = storage; this.identity = {...identity}; this.revision = revision;
            this.key = `llt:short-reading:${identity.account}:${identity.book}:${identity.chapter}:${revision}`;
            this.unavailable = !storage; this.readFailed = !storage;
        }
        load(practice) {
            let raw;
            try { raw = this.storage.getItem(this.key); }
            catch (_) { this.unavailable = true; this.readFailed = true; return false; }
            try {
                const value = JSON.parse(raw);
                if (!value || value.version !== 1 || value.revision !== this.revision ||
                    !['account', 'book', 'chapter'].every(key => String(value[key]) === String(this.identity[key]))) return false;
                return practice.restore(value.state);
            } catch (_) { return false; }
        }
        save(practice) {
            try {
                this.storage.setItem(this.key, JSON.stringify({version: 1, ...this.identity, revision: this.revision, state: practice.snapshot()}));
                this.unavailable = this.readFailed; return !this.unavailable;
            } catch (_) { this.unavailable = true; return false; }
        }
    }
    async function mount(doc) {
        const panel = doc.getElementById('short-reading-practice');
        const data = doc.getElementById('short-reading-data');
        if (!panel || !data) return;
        let practice, reading;
        try { reading = JSON.parse(data.textContent); practice = new Practice(reading.questions); }
        catch (_) {
            panel.textContent = 'Не удалось открыть вопросы к тексту. Обнови страницу.';
            return;
        }
        let store, unavailable = false, invalid = false, unloadGuarded = false, serverSaved = false;
        const view = doc.defaultView;
        try {
            const revision = await contentDigest({reading, text: doc.getElementById('chapterContent')?.textContent || ''});
            let storage;
            try { storage = view.localStorage; } catch (_) {}
            store = new DraftStore(storage, {account: panel.dataset.account, book: panel.dataset.book, chapter: panel.dataset.chapter}, revision);
            store.load(practice); unavailable = store.unavailable;
        } catch (_) { unavailable = true; }
        const beforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
        function updateWarning() {
            const warning = doc.getElementById('short-reading-draft-warning');
            if (warning) warning.hidden = !unavailable || serverSaved;
            const dirty = !invalid && !serverSaved && unavailable && (practice.answers.length || practice.selection || practice.completed);
            if (dirty && !unloadGuarded) { view.addEventListener('beforeunload', beforeUnload); unloadGuarded = true; }
            else if (!dirty && unloadGuarded) { view.removeEventListener('beforeunload', beforeUnload); unloadGuarded = false; }
        }
        function persist() {
            if (!invalid && store) { store.save(practice); unavailable = store.unavailable; }
            updateWarning();
        }
        view.addEventListener('llt:account-changed', () => { invalid = true; updateWarning(); });
        doc.addEventListener('shortReadingFinishSaved', () => { serverSaved = true; updateWarning(); });
        function node(tag, text, className) {
            const value = doc.createElement(tag);
            if (text) value.textContent = text;
            if (className) value.className = className;
            return value;
        }
        function render(focusFeedback) {
            panel.replaceChildren();
            panel.append(node('h2', 'Проверим понимание'));
            panel.append(node('p', 'Можно вернуться к тексту выше. Ошибка — повод перечитать нужное место.'));
            const warning = node('p', 'Не удалось сохранить ответы в браузере. Они остаются в этой вкладке. Не закрывай и не обновляй её до завершения чтения.', 'alert alert-warning');
            warning.id = 'short-reading-draft-warning'; warning.setAttribute('role', 'status'); panel.append(warning);
            updateWarning();
            if (practice.completed) {
                panel.append(node('p', 'Все вопросы разобраны. Можно завершить чтение.', 'short-reading-success'));
                doc.dispatchEvent(new CustomEvent('shortReadingPracticeComplete'));
                return;
            }
            const q = practice.question;
            panel.append(node('p', `Вопрос ${practice.index + 1} из ${practice.questions.length}`, 'short-reading-position'));
            panel.append(node('p', q.instruction));
            const group = node('fieldset');
            group.append(node('legend', q.prompt));
            group.append(node('p', q.prompt_translation));
            const check = node('button', 'Проверить ответ', 'rdr-bottom-btn rdr-bottom-btn--primary');
            check.type = 'button';
            check.id = 'short-reading-check';
            check.disabled = !practice.selection;
            for (const option of q.options) {
                const label = node('label', '', 'short-reading-option');
                const radio = node('input');
                radio.type = 'radio'; radio.name = 'short-reading-answer'; radio.value = option.id;
                radio.checked = practice.selection === option.id;
                radio.disabled = Boolean(practice.feedback);
                radio.addEventListener('change', () => { practice.choose(option.id); check.disabled = false; persist(); });
                label.append(radio, node('span', option.text));
                group.append(label);
            }
            panel.append(group);
            if (practice.feedback) {
                const feedback = node('div', '', 'short-reading-feedback');
                feedback.id = 'short-reading-feedback'; feedback.setAttribute('role', 'status');
                feedback.setAttribute('tabindex', '-1');
                feedback.append(node('strong', practice.feedback.correct ? 'Верно' : 'Посмотрим ещё раз'));
                feedback.append(node('p', practice.feedback.explanation));
                panel.append(feedback);
                const next = node('button', practice.feedback.correct
                    ? (practice.index + 1 === practice.questions.length ? 'Завершить проверку' : 'Следующий вопрос')
                    : 'Попробовать ещё раз', 'rdr-bottom-btn rdr-bottom-btn--primary');
                next.type = 'button'; next.id = 'short-reading-continue';
                next.addEventListener('click', () => { practice.continue(); persist(); render(false); });
                panel.append(next);
                if (focusFeedback) feedback.focus({preventScroll: true});
            } else {
                check.addEventListener('click', () => { practice.check(); persist(); render(true); });
                panel.append(check);
            }
        }
        render(false);
    }
    return {Practice, DraftStore, contentDigest, mount};
});
