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
        restart() { this.index = 0; this.selection = null; this.feedback = null; this.completed = false; }
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
                if (this.index + 1 === this.questions.length) this.completed = true;
                else this.index += 1;
            }
            this.selection = null;
            this.feedback = null;
        }
    }
    function mount(doc) {
        const panel = doc.getElementById('short-reading-practice');
        const data = doc.getElementById('short-reading-data');
        if (!panel || !data) return;
        let practice;
        try { practice = new Practice(JSON.parse(data.textContent).questions); }
        catch (_) {
            panel.textContent = 'Не удалось открыть вопросы к тексту. Обнови страницу.';
            return;
        }
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
                radio.addEventListener('change', () => { practice.choose(option.id); check.disabled = false; });
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
                next.addEventListener('click', () => { practice.continue(); render(false); });
                panel.append(next);
                if (focusFeedback) feedback.focus({preventScroll: true});
            } else {
                check.addEventListener('click', () => { practice.check(); render(true); });
                panel.append(check);
            }
        }
        render(false);
    }
    return {Practice, mount};
});
