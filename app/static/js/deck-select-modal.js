/**
 * DeckSelectModal - Modal component for selecting a deck when adding words
 *
 * Usage:
 *   deckSelectModal.show(wordId, callback, options)
 *   deckSelectModal.showBulk(wordIds, callback, options)
 *   deckSelectModal.showCreateFirst(callback)
 *
 * The callback receives: { deckId: number, deckName: string }
 * Options: { forceDecks: true } - hides "study only" option
 */

class DeckSelectModal {
    constructor() {
        this.modal = null;
        this.modalElement = null;
        this.decks = [];
        this.onSelect = null;
        this.wordIds = [];
        this.isBulk = false;
        this.isCreatingDeck = false;
        this.forceDecks = false;

        // Create modal element on initialization
        this._createModalElement();
    }

    /**
     * Create the modal HTML element
     */
    _createModalElement() {
        // Check if modal already exists
        if (document.getElementById('deckSelectModal')) {
            this.modalElement = document.getElementById('deckSelectModal');
            this.modal = new bootstrap.Modal(this.modalElement);
            return;
        }

        const modalHTML = `
            <div class="modal fade" id="deckSelectModal" tabindex="-1" aria-labelledby="deckSelectModalLabel" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header border-0 pb-0">
                            <h5 class="modal-title fw-bold" id="deckSelectModalLabel">Добавить в колоду</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button>
                        </div>
                        <div class="modal-body pt-2">
                            <p class="text-muted mb-3 deck-modal-subtitle">
                                Выберите колоду или добавьте только в изучение
                            </p>

                            <!-- Study Only Option -->
                            <button class="deck-option deck-option-primary w-100 mb-3" data-deck-id="">
                                <div class="d-flex align-items-center">
                                    <div class="deck-option-icon bg-primary">
                                        <i class="fas fa-graduation-cap"></i>
                                    </div>
                                    <div class="deck-option-content">
                                        <div class="deck-option-title">Только в изучение</div>
                                        <div class="deck-option-desc">Добавить в систему SRS без колоды</div>
                                    </div>
                                </div>
                            </button>

                            <!-- Deck List -->
                            <div class="deck-list-container">
                                <div class="deck-list-header d-flex justify-content-between align-items-center mb-2">
                                    <span class="text-muted small">Мои колоды</span>
                                    <button class="btn btn-sm btn-link text-decoration-none p-0 deck-create-toggle">
                                        <i class="fas fa-plus me-1"></i>Создать
                                    </button>
                                </div>

                                <!-- Create Deck Form (hidden by default) -->
                                <div class="deck-create-form mb-3" style="display: none;">
                                    <div class="input-group">
                                        <input type="text" class="form-control deck-create-input" placeholder="Название новой колоды" maxlength="200">
                                        <button class="btn btn-primary deck-create-submit" type="button">
                                            <i class="fas fa-check"></i>
                                        </button>
                                        <button class="btn btn-outline-secondary deck-create-cancel" type="button">
                                            <i class="fas fa-times"></i>
                                        </button>
                                    </div>
                                </div>

                                <!-- Deck List Items -->
                                <div class="deck-list">
                                    <div class="deck-list-loading text-center py-3">
                                        <div class="spinner-border spinner-border-sm text-primary" role="status">
                                            <span class="visually-hidden">Загрузка...</span>
                                        </div>
                                    </div>
                                </div>

                                <!-- Empty State -->
                                <div class="deck-list-empty text-center py-3" style="display: none;">
                                    <i class="fas fa-folder-open text-muted mb-2" style="font-size: 2rem;"></i>
                                    <p class="text-muted mb-0">У вас пока нет колод</p>
                                    <small class="text-muted">Создайте первую колоду выше</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHTML);
        this.modalElement = document.getElementById('deckSelectModal');
        this.modal = new bootstrap.Modal(this.modalElement);

        // Setup event handlers
        this._setupEventHandlers();
    }

    /**
     * Setup event handlers for the modal
     */
    _setupEventHandlers() {
        // Study only option click
        const studyOnlyBtn = this.modalElement.querySelector('[data-deck-id=""]');
        studyOnlyBtn.addEventListener('click', () => {
            this._selectDeck(null, null);
        });

        // Toggle create deck form
        const createToggle = this.modalElement.querySelector('.deck-create-toggle');
        const createForm = this.modalElement.querySelector('.deck-create-form');
        const createInput = this.modalElement.querySelector('.deck-create-input');
        const createSubmit = this.modalElement.querySelector('.deck-create-submit');
        const createCancel = this.modalElement.querySelector('.deck-create-cancel');

        createToggle.addEventListener('click', () => {
            createForm.style.display = 'block';
            createToggle.style.display = 'none';
            createInput.focus();
        });

        createCancel.addEventListener('click', () => {
            createForm.style.display = 'none';
            createToggle.style.display = 'inline-block';
            createInput.value = '';
        });

        createSubmit.addEventListener('click', () => this._createDeck());

        createInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this._createDeck();
            }
        });

        // Modal hidden event - reset state
        this.modalElement.addEventListener('hidden.bs.modal', () => {
            createForm.style.display = 'none';
            createToggle.style.display = 'inline-block';
            createInput.value = '';

            // Reset forceDecks state
            this._setForceDecks(false);

            // Reset title and subtitle
            this.modalElement.querySelector('#deckSelectModalLabel').textContent = 'Добавить в колоду';
            this.modalElement.querySelector('.deck-modal-subtitle').textContent = 'Выберите колоду или добавьте только в изучение';

            // Show deck list container
            this.modalElement.querySelector('.deck-list-container').style.display = 'block';
        });
    }

    /**
     * Set forceDecks mode - hides/shows "study only" button
     */
    _setForceDecks(force) {
        this.forceDecks = force;
        const studyOnlyBtn = this.modalElement.querySelector('[data-deck-id=""]');
        studyOnlyBtn.style.display = force ? 'none' : 'block';
    }

    /**
     * Load user's decks from API
     */
    async _loadDecks() {
        const deckList = this.modalElement.querySelector('.deck-list');
        const emptyState = this.modalElement.querySelector('.deck-list-empty');

        deckList.innerHTML = `
            <div class="deck-list-loading text-center py-3">
                <div class="spinner-border spinner-border-sm text-primary" role="status">
                    <span class="visually-hidden">Загрузка...</span>
                </div>
            </div>
        `;
        emptyState.style.display = 'none';

        try {
            const response = await fetch('/study/api/my-decks');
            const data = await response.json();

            if (data.success && data.decks) {
                this.decks = data.decks;
                this._renderDecks();
            } else {
                throw new Error('Failed to load decks');
            }
        } catch (error) {
            console.error('Error loading decks:', error);
            deckList.innerHTML = `
                <div class="text-center py-3 text-danger">
                    <i class="fas fa-exclamation-circle me-2"></i>
                    Ошибка загрузки колод
                </div>
            `;
        }
    }

    /**
     * Render the deck list
     */
    _renderDecks() {
        const deckList = this.modalElement.querySelector('.deck-list');
        const emptyState = this.modalElement.querySelector('.deck-list-empty');

        if (this.decks.length === 0) {
            deckList.innerHTML = '';
            emptyState.style.display = 'block';
            return;
        }

        emptyState.style.display = 'none';

        const decksHTML = this.decks.map(deck => `
            <button class="deck-option w-100 mb-2" data-deck-id="${deck.id}">
                <div class="d-flex align-items-center">
                    <div class="deck-option-icon bg-secondary">
                        <i class="fas fa-layer-group"></i>
                    </div>
                    <div class="deck-option-content flex-grow-1">
                        <div class="deck-option-title">${this._escapeHtml(deck.name)}</div>
                        <div class="deck-option-desc">${deck.word_count} слов</div>
                    </div>
                    ${deck.is_public ? '<span class="badge bg-info ms-2">Публичная</span>' : ''}
                </div>
            </button>
        `).join('');

        deckList.innerHTML = decksHTML;

        // Add click handlers to deck options
        deckList.querySelectorAll('.deck-option').forEach(btn => {
            btn.addEventListener('click', () => {
                const deckId = parseInt(btn.dataset.deckId);
                const deckName = btn.querySelector('.deck-option-title').textContent;
                this._selectDeck(deckId, deckName);
            });
        });
    }

    /**
     * Create a new deck via API
     */
    async _createDeck() {
        if (this.isCreatingDeck) return;

        const input = this.modalElement.querySelector('.deck-create-input');
        const name = input.value.trim();

        if (!name) {
            input.classList.add('is-invalid');
            return;
        }

        input.classList.remove('is-invalid');
        this.isCreatingDeck = true;

        const submitBtn = this.modalElement.querySelector('.deck-create-submit');
        const originalContent = submitBtn.innerHTML;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
        submitBtn.disabled = true;

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');

            const response = await fetch('/study/api/decks/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken || ''
                },
                body: JSON.stringify({ name })
            });

            const data = await response.json();

            if (data.success && data.deck) {
                // Add to decks list and select it
                this.decks.unshift(data.deck);
                this._renderDecks();

                // Hide create form
                const createForm = this.modalElement.querySelector('.deck-create-form');
                const createToggle = this.modalElement.querySelector('.deck-create-toggle');
                createForm.style.display = 'none';
                createToggle.style.display = 'inline-block';
                input.value = '';

                // Auto-select the new deck
                this._selectDeck(data.deck.id, data.deck.name);
            } else {
                throw new Error(data.error || 'Failed to create deck');
            }
        } catch (error) {
            console.error('Error creating deck:', error);
            alert('Ошибка при создании колоды: ' + error.message);
        } finally {
            submitBtn.innerHTML = originalContent;
            submitBtn.disabled = false;
            this.isCreatingDeck = false;
        }
    }

    /**
     * Select a deck and call the callback
     */
    _selectDeck(deckId, deckName) {
        this.modal.hide();

        if (this.onSelect) {
            this.onSelect({
                deckId,
                deckName,
                wordIds: this.wordIds,
                isBulk: this.isBulk
            });
        }
    }

    /**
     * Escape HTML to prevent XSS
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Show modal for "create first deck" scenario (0 decks)
     * @param {function} callback - Called with { deckId, deckName }
     */
    showCreateFirst(callback) {
        this.wordIds = [];
        this.isBulk = false;
        this.isSetDefault = false;
        this.onSelect = callback;

        // Update title and subtitle
        this.modalElement.querySelector('#deckSelectModalLabel').textContent = 'Создайте первую колоду';
        const subtitle = this.modalElement.querySelector('.deck-modal-subtitle');
        subtitle.textContent = 'Для добавления слов нужна хотя бы одна колода';

        // Hide "study only" button
        this._setForceDecks(true);

        // Hide deck list container (no decks to show), show only create form
        const deckListContainer = this.modalElement.querySelector('.deck-list-container');
        deckListContainer.style.display = 'block';

        // Hide deck list and empty state, show only create form
        const deckList = this.modalElement.querySelector('.deck-list');
        const emptyState = this.modalElement.querySelector('.deck-list-empty');
        const deckListHeader = this.modalElement.querySelector('.deck-list-header');
        deckList.innerHTML = '';
        emptyState.style.display = 'none';
        deckListHeader.style.display = 'none';

        // Show create form expanded with autofocus
        const createForm = this.modalElement.querySelector('.deck-create-form');
        const createToggle = this.modalElement.querySelector('.deck-create-toggle');
        const createInput = this.modalElement.querySelector('.deck-create-input');
        createForm.style.display = 'block';
        createToggle.style.display = 'none';
        createInput.value = '';

        this.modal.show();

        // Autofocus after modal is shown
        this.modalElement.addEventListener('shown.bs.modal', () => {
            createInput.focus();
        }, { once: true });
    }

    /**
     * Show modal for single word
     * @param {number} wordId - Word ID to add
     * @param {function} callback - Called with { deckId, deckName }
     * @param {Object} options - Options: { forceDecks: boolean }
     */
    show(wordId, callback, options = {}) {
        this.wordIds = [wordId];
        this.isBulk = false;
        this.isSetDefault = false;
        this.onSelect = callback;

        // Apply forceDecks option
        if (options.forceDecks) {
            this._setForceDecks(true);
        }

        // Update subtitle
        const subtitle = this.modalElement.querySelector('.deck-modal-subtitle');
        subtitle.textContent = options.forceDecks
            ? 'Выберите колоду для добавления слова'
            : 'Выберите колоду или добавьте только в изучение';

        // Hide "set as default" checkbox
        this._toggleDefaultCheckbox(false);

        // Restore deck list header visibility
        const deckListHeader = this.modalElement.querySelector('.deck-list-header');
        deckListHeader.style.display = '';

        this._loadDecks();
        this.modal.show();
    }

    /**
     * Show modal with option to set as default
     * @param {number|null} wordId - Word ID to add (null if just setting default)
     * @param {function} callback - Called with { deckId, deckName }
     * @param {boolean} showSetDefault - Whether to show "set as default" option
     * @param {Object} options - Options: { forceDecks: boolean }
     */
    showWithCallback(wordId, callback, showSetDefault = false, options = {}) {
        this.wordIds = wordId ? [wordId] : [];
        this.isBulk = false;
        this.isSetDefault = showSetDefault;
        this.onSelect = callback;

        // Apply forceDecks option
        if (options.forceDecks) {
            this._setForceDecks(true);
        }

        // Update subtitle
        const subtitle = this.modalElement.querySelector('.deck-modal-subtitle');
        if (showSetDefault) {
            subtitle.innerHTML = '<strong>Выберите колоду по умолчанию</strong><br><small class="text-muted">Это действие будет применяться автоматически</small>';
        } else {
            subtitle.textContent = options.forceDecks
                ? 'Выберите колоду для добавления слова'
                : 'Выберите колоду или добавьте только в изучение';
        }

        // Show/hide "set as default" checkbox
        this._toggleDefaultCheckbox(showSetDefault);

        // Restore deck list header visibility
        const deckListHeader = this.modalElement.querySelector('.deck-list-header');
        deckListHeader.style.display = '';

        this._loadDecks();
        this.modal.show();
    }

    /**
     * Toggle the "set as default" checkbox visibility
     */
    _toggleDefaultCheckbox(show) {
        let checkbox = this.modalElement.querySelector('.set-default-checkbox');

        if (show && !checkbox) {
            // Create checkbox if doesn't exist
            const studyOnlyBtn = this.modalElement.querySelector('[data-deck-id=""]');
            const checkboxHtml = `
                <div class="set-default-checkbox form-check mt-3 pt-3 border-top">
                    <input type="checkbox" class="form-check-input" id="setAsDefaultDeck" checked>
                    <label class="form-check-label text-muted small" for="setAsDefaultDeck">
                        Запомнить выбор и использовать по умолчанию
                    </label>
                </div>
            `;
            studyOnlyBtn.insertAdjacentHTML('afterend', checkboxHtml);
        } else if (checkbox) {
            checkbox.style.display = show ? 'block' : 'none';
            if (show) {
                checkbox.querySelector('input').checked = true;
            }
        }
    }

    /**
     * Show modal for bulk words
     * @param {number[]} wordIds - Array of word IDs to add
     * @param {function} callback - Called with { deckId, deckName, wordIds }
     * @param {Object} options - Options: { forceDecks: boolean }
     */
    showBulk(wordIds, callback, options = {}) {
        this.wordIds = wordIds;
        this.isBulk = true;
        this.isSetDefault = false;
        this.onSelect = callback;

        // Apply forceDecks option
        if (options.forceDecks) {
            this._setForceDecks(true);
        }

        // Update subtitle
        const subtitle = this.modalElement.querySelector('.deck-modal-subtitle');
        subtitle.textContent = `Добавить ${wordIds.length} слов в колоду`;

        // Hide "set as default" checkbox
        this._toggleDefaultCheckbox(false);

        // Restore deck list header visibility
        const deckListHeader = this.modalElement.querySelector('.deck-list-header');
        deckListHeader.style.display = '';

        this._loadDecks();
        this.modal.show();
    }

    /**
     * Hide the modal
     */
    hide() {
        this.modal.hide();
    }
}

// Create global instance
window.deckSelectModal = new DeckSelectModal();
