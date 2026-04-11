/**
 * Word Translator — click-to-translate for English words.
 * Wraps English words in clickable spans, shows popup with translation,
 * audio playback, and "Add to study" button.
 *
 * Usage:
 *   new WordTranslator({ container: '#my-text-container' });
 */
class WordTranslator {
    constructor(options = {}) {
        this.containerSelector = options.container || '.text-container';
        this.container = document.querySelector(this.containerSelector);
        if (!this.container) return;

        this.popup = null;
        this.currentAudio = null;
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        this._createPopup();
        this._processContent();
        this._bindEvents();
    }

    _createPopup() {
        const popup = document.createElement('div');
        popup.className = 'wt-popup';
        popup.innerHTML = `
            <div class="wt-popup__content">
                <div class="wt-popup__header">
                    <span class="wt-popup__word" id="wtPopupWord"></span>
                    <button class="wt-popup__audio-btn" id="wtPlayAudio" style="display:none">
                        <i class="fas fa-volume-up"></i>
                    </button>
                    <button class="wt-popup__close" id="wtClosePopup">&times;</button>
                </div>
                <div class="wt-popup__body">
                    <div class="wt-popup__translation" id="wtTranslation"></div>
                    <div class="wt-popup__form-info" id="wtFormInfo" style="display:none"></div>
                </div>
                <div class="wt-popup__actions">
                    <button class="wt-popup__learn-btn" id="wtAddToStudy" style="display:none">
                        <i class="fas fa-plus"></i> Изучать
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(popup);
        this.popup = popup;

        this.els = {
            word: popup.querySelector('#wtPopupWord'),
            translation: popup.querySelector('#wtTranslation'),
            formInfo: popup.querySelector('#wtFormInfo'),
            audioBtn: popup.querySelector('#wtPlayAudio'),
            learnBtn: popup.querySelector('#wtAddToStudy'),
            closeBtn: popup.querySelector('#wtClosePopup'),
        };
    }

    _processContent() {
        const elements = this.container.querySelectorAll('p, h1, h2, h3, h4, h5, h6, .listening-content-text, .prose-container, .reading-line-text, div.dialogue-line-text');
        elements.forEach(el => {
            if (el.getAttribute('data-wt-processed')) return;
            el.innerHTML = el.innerHTML.replace(
                /\b([a-zA-Z]{2,})\b(?![^<]*>|[^<>]*<\/)/g,
                '<span class="wt-word" data-word="$1">$1</span>'
            );
            el.setAttribute('data-wt-processed', 'true');
        });
    }

    _bindEvents() {
        // Word clicks via delegation
        this.container.addEventListener('click', (e) => {
            if (e.target.classList.contains('wt-word')) {
                e.preventDefault();
                this._handleWordClick(e.target);
            }
        });

        // Close popup
        this.els.closeBtn.addEventListener('click', () => this._hidePopup());
        document.addEventListener('click', (e) => {
            if (!this.popup.contains(e.target) && !e.target.classList.contains('wt-word')) {
                this._hidePopup();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this._hidePopup();
        });

        // Audio
        this.els.audioBtn.addEventListener('click', () => this._playAudio());

        // Add to study
        this.els.learnBtn.addEventListener('click', () => this._addToStudy());
    }

    async _handleWordClick(el) {
        const word = el.getAttribute('data-word').toLowerCase();

        // Highlight
        this.container.querySelectorAll('.wt-word.wt-selected').forEach(w => w.classList.remove('wt-selected'));
        el.classList.add('wt-selected');

        // Show loading state
        this.els.word.textContent = el.getAttribute('data-word');
        this.els.translation.textContent = 'Загрузка...';
        this.els.formInfo.style.display = 'none';
        this.els.audioBtn.style.display = 'none';
        this.els.learnBtn.style.display = 'none';
        this._showPopup(el);

        try {
            const resp = await fetch(`/api/word-translation/${encodeURIComponent(word)}`, {
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });

            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            const contentType = resp.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Not JSON');
            }

            const data = await resp.json();

            if (data && data.translation) {
                this.els.translation.textContent = data.translation;

                if (data.is_form && data.form_text && data.base_form) {
                    this.els.formInfo.textContent = `${data.form_text} "${data.base_form}"`;
                    this.els.formInfo.style.display = 'block';
                }

                if (data.has_audio && data.audio_url) {
                    this.els.audioBtn.style.display = 'flex';
                    this.els.audioBtn.setAttribute('data-audio-url', data.audio_url);
                }

                if (data.id && !data.in_reading_deck) {
                    this.els.learnBtn.style.display = 'flex';
                    this.els.learnBtn.setAttribute('data-word-id', data.id);
                }

                // Auto-play audio
                if (data.has_audio && data.audio_url) {
                    setTimeout(() => this._playAudio(), 300);
                }
            } else {
                this.els.translation.textContent = 'Слово не найдено в словаре';
            }
        } catch (err) {
            this.els.translation.textContent = 'Перевод недоступен';
        }
    }

    _showPopup(el) {
        this.popup.classList.add('wt-popup--active');
        this._positionPopup(el);
    }

    _hidePopup() {
        this.popup.classList.remove('wt-popup--active');
        this.container.querySelectorAll('.wt-word.wt-selected').forEach(w => w.classList.remove('wt-selected'));
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }
    }

    _positionPopup(el) {
        if (window.innerWidth <= 768) {
            // Mobile: bottom sheet
            this.popup.style.position = 'fixed';
            this.popup.style.top = '';
            this.popup.style.left = '0';
            this.popup.style.right = '0';
            this.popup.style.bottom = '0';
            return;
        }

        // Desktop: near clicked word
        const rect = el.getBoundingClientRect();
        const popupWidth = 320;
        const popupHeight = 200;

        let top = rect.bottom + 8;
        let left = rect.left;

        if (left + popupWidth > window.innerWidth) {
            left = window.innerWidth - popupWidth - 10;
        }
        if (left < 10) left = 10;

        if (top + popupHeight > window.innerHeight) {
            top = rect.top - popupHeight - 8;
            if (top < 10) top = 10;
        }

        this.popup.style.position = 'fixed';
        this.popup.style.top = `${top}px`;
        this.popup.style.left = `${left}px`;
        this.popup.style.right = '';
        this.popup.style.bottom = '';
    }

    _playAudio() {
        const url = this.els.audioBtn.getAttribute('data-audio-url');
        if (!url) return;
        if (this.currentAudio) this.currentAudio.pause();
        this.currentAudio = new Audio(url);
        this.currentAudio.play().catch(() => {});
    }

    async _addToStudy() {
        const wordId = this.els.learnBtn.getAttribute('data-word-id');
        if (!wordId) return;

        const headers = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
        if (this.csrfToken) headers['X-CSRFToken'] = this.csrfToken;

        try {
            const resp = await fetch('/api/add-to-learning', {
                method: 'POST',
                headers,
                credentials: 'same-origin',
                body: JSON.stringify({ word_id: parseInt(wordId) })
            });

            const data = await resp.json();
            if (data.success) {
                this.els.learnBtn.textContent = '';
                var icon = document.createElement('i');
                icon.className = 'fas fa-check';
                this.els.learnBtn.appendChild(icon);
                this.els.learnBtn.appendChild(document.createTextNode(' Добавлено'));
                this.els.learnBtn.disabled = true;
                this.els.learnBtn.classList.add('wt-popup__learn-btn--done');
            }
        } catch (err) {
            this.els.learnBtn.textContent = 'Ошибка';
        }
    }
}
