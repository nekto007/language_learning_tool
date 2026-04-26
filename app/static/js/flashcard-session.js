/**
 * FlashcardSession - Shared flashcard engine
 * Extracted from study/cards.html
 *
 * Supports both AJAX card loading (study module) and
 * server-side pre-loaded cards (curriculum, book-courses).
 */
class FlashcardSession {
    constructor(config) {
        this.config = {
            cards: [],                      // Initial cards array (server-side)
            fetchCardsUrl: null,            // URL to fetch cards via AJAX (null = use inline cards)
            fetchCardsParams: {},           // Extra params for AJAX fetch
            gradeUrl: '/study/api/update-study-item',  // API to send rating
            gradePayload: null,             // Function(card, rating, sessionId, extraParams) => request body
            completeUrl: null,              // API for session completion (null = skip)
            completePayload: null,          // Function(sessionId) => request body
            onComplete: null,               // Callback(data) after completion
            markLessonCompleteUrl: null,    // API to mark lesson done
            sessionId: null,
            backUrl: '/',
            title: 'Карточки',
            showBookContext: false,
            showExamples: true,
            showTranslations: true,
            showAudio: true,
            onCompleteUrl: '/',
            onCompleteText: 'Продолжить',
            nothingToStudy: false,          // Show empty state
            limitReached: false,            // Show limit state
            dailyLimit: 20,
            newCardsToday: 0,
            deckId: null,
            extraStudy: false,
            lessonMode: false,
            ...config
        };

        // Default gradePayload if not provided
        if (!this.config.gradePayload) {
            this.config.gradePayload = (card, rating, sessionId, extraParams) => ({
                word_id: card.word_id,
                direction: card.direction,
                quality: rating,
                session_id: sessionId,
                is_new: card.is_new,
                deck_id: extraParams.deckId,
                extra_study: extraParams.extraStudy,
                lesson_mode: extraParams.lessonMode || false
            });
        }

        // Default completePayload if not provided
        if (!this.config.completePayload && this.config.completeUrl) {
            this.config.completePayload = (sessionId) => ({
                session_id: sessionId
            });
        }

        // App state
        this.originalCards = [];
        this.cards = [];
        this.currentCardIndex = 0;
        this.sessionStartTime = Date.now();
        this.sessionStats = {
            total: 0,
            correct: 0,
            incorrect: 0,
            new_cards: 0,
            learning_cards: 0,
            review_cards: 0
        };
        this.hintTimeout = null;

        // Anti-repeat: track recently shown card IDs
        this.recentCardIds = [];
        this.RECENT_CARDS_LIMIT = 5;

        // Track if more cards are available (for extra study option)
        this.hasMoreNewCards = false;
        this.hasMoreReviewCards = false;

        // Session attempts tracking for requeue limit (max 3 shows per card)
        this.sessionAttempts = {};
        this.MAX_SESSION_ATTEMPTS = 3;

        // State configuration for display
        this.STATE_CONFIG = {
            'new': { label: 'НОВАЯ', class: 'bg-info', color: '#17a2b8' },
            'learning': { label: 'ИЗУЧЕНИЕ', class: 'bg-warning text-dark', color: '#ffc107' },
            'review': { label: 'ПОВТОР', class: 'bg-success', color: '#28a745' },
            'relearning': { label: 'ПЕРЕУЧИВАНИЕ', class: 'bg-danger', color: '#dc3545' }
        };

        // Fun completion messages
        this.completionMessages = [
            'Done',
            'Готово.',
            'Красава.',
            'Good job.',
            'Nice.',
            'Keep going.',
            'Едем дальше.',
            'Mission complete',
            'Brain gains',
            'Vocabulary +1. Легенда.',
            'Карточки? Разобрал(а).',
            'Ты держишь темп — это круто.',
            'Маленькая победа дня',
            'Твой английский растёт',
            'Flipped. Learned. Dominated.'
        ];

        // DOM elements (assigned in init)
        this.els = {};

        // Initialize
        this.init();
    }

    /**
     * Initialize: setup DOM references, load cards, bind events.
     */
    init() {
        this._cacheDom();
        this._bindEvents();
        this._removeTapDelay();

        // If nothing to study, show message immediately
        if (this.config.nothingToStudy) {
            this.els.loadingSpinner.style.display = 'none';
            const progressSection = this.els.progressSection;
            if (progressSection) progressSection.style.display = 'none';
            const nothingEl = document.getElementById('nothing-to-study');
            if (nothingEl) nothingEl.style.display = 'block';
            return;
        }

        // Load cards
        this._loadCards();
    }

    /**
     * Cache DOM element references.
     */
    _cacheDom() {
        this.els = {
            flashcardView: document.getElementById('flashcard-view'),
            cardFront: document.getElementById('card-front'),
            cardBack: document.getElementById('card-back'),
            frontWord: document.getElementById('front-word'),
            backWord: document.getElementById('back-word'),
            frontAudioBtn: document.getElementById('front-audio-btn'),
            backAudioBtn: document.getElementById('back-audio-btn'),
            translationText: document.getElementById('translation-text'),
            examplesContainer: document.getElementById('examples-container'),
            exampleText: document.getElementById('example-text'),
            exampleTranslation: document.getElementById('example-translation'),
            hintText: document.getElementById('hint-text'),
            leechHint: document.getElementById('leech-hint'),
            leechHintText: document.getElementById('leech-hint-text'),
            cardCounter: document.getElementById('card-counter'),
            newCardsCounter: document.getElementById('new-cards-counter'),
            studiedCardsCounter: document.getElementById('studied-cards-counter'),
            reviewCardsCounter: document.getElementById('review-cards-counter'),
            progressFill: document.getElementById('progress-fill'),
            showAnswerBtn: document.getElementById('show-answer-btn'),
            loadingSpinner: document.getElementById('loading-spinner'),
            noCardsMessage: document.getElementById('no-cards-message'),
            dailyLimitMessage: document.getElementById('daily-limit-message'),
            sessionComplete: document.getElementById('session-complete'),
            wordAudio: document.getElementById('word-audio'),
            endSessionBtn: document.getElementById('end-session-btn'),
            newCardsStats: document.getElementById('new-cards-stats'),
            reviewsStats: document.getElementById('reviews-stats'),
            stateBadge: document.getElementById('state-badge'),
            lapsesBadge: document.getElementById('lapses-badge'),
            progressSection: document.querySelector('.cards-progress-section'),
            bookContext: document.getElementById('book-context'),
            bookContextText: document.getElementById('book-context-text'),
            unitTypeBadge: document.getElementById('unit-type-badge'),
            cardNote: document.getElementById('card-note'),
            cardNoteText: document.getElementById('card-note-text'),
        };
    }

    /**
     * Bind event listeners.
     */
    _bindEvents() {
        const self = this;

        // Show answer button
        if (this.els.showAnswerBtn) {
            this.els.showAnswerBtn.addEventListener('click', () => self.flipCard());
        }

        // Audio buttons
        if (this.els.frontAudioBtn) {
            this.els.frontAudioBtn.addEventListener('click', () => {
                if (self.els.wordAudio) self.els.wordAudio.play();
            });
        }
        if (this.els.backAudioBtn) {
            this.els.backAudioBtn.addEventListener('click', () => {
                if (self.els.wordAudio) self.els.wordAudio.play();
            });
        }

        // Rating buttons
        document.querySelectorAll('.rating-btn').forEach(button => {
            button.addEventListener('click', function() {
                const rating = parseInt(this.getAttribute('data-rating'));
                self.rateCard(rating);
            });
        });

        // End session button
        if (this.els.endSessionBtn) {
            this.els.endSessionBtn.addEventListener('click', () => {
                if (confirm('Вы уверены, что хотите завершить сессию?')) {
                    try {
                        self.completeSession();
                    } catch (e) {
                        console.error('Error in complete session:', e);
                        window.location.href = self.config.backUrl;
                    }
                }
            });
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => self._handleKeydown(e));
    }

    /**
     * Remove 300ms tap delay on touch devices.
     */
    _removeTapDelay() {
        // Modern browsers handle this via touch-action: manipulation or viewport meta,
        // but we ensure click handlers are responsive
        document.addEventListener('touchstart', function() {}, { passive: true });
    }

    /**
     * Handle keyboard shortcuts.
     */
    _handleKeydown(e) {
        const { cardBack, cardFront } = this.els;

        // Rating shortcuts when card back is visible
        if (cardBack && cardBack.style.display === 'flex') {
            if (e.key === '1') {
                e.preventDefault();
                this.rateCard(1);
            } else if (e.key === '2') {
                e.preventDefault();
                this.rateCard(2);
            } else if (e.key === '3') {
                e.preventDefault();
                this.rateCard(3);
            }
        }
        // Show answer when front card is visible and spacebar is pressed
        else if (cardFront && cardFront.style.display === 'flex' && e.code === 'Space') {
            e.preventDefault();
            this.flipCard();
        }
        // Ctrl+Shift+X for emergency exit
        else if (e.ctrlKey && e.shiftKey && e.key === 'X') {
            window.location.href = this.config.backUrl;
        }
    }

    /**
     * Load cards - either from AJAX or from inline config.
     */
    async _loadCards() {
        try {
            if (this.config.fetchCardsUrl) {
                this.originalCards = await this.fetchCards();
            } else {
                // Use pre-loaded cards from config
                this.originalCards = (this.config.cards || []).filter(
                    card => card.translation && card.translation.trim() !== ''
                );
            }

            // Check if a message was already shown during fetch
            if (this._noCardsMessageShown) {
                return;
            }

            if (!this.originalCards || this.originalCards.length === 0) {
                this._showNoCardsMessage();
                return;
            }

            // Create alternating cards
            this.cards = this.createAlternatingCards(this.originalCards);

            if (!this.cards || this.cards.length === 0) {
                this._showNoCardsMessage();
                return;
            }

            // Normalize: accept both 'state' and 'status' field names
            for (const card of this.cards) {
                if (!card.state && card.status) {
                    card.state = card.status;
                }
                if (!card.state) {
                    card.state = 'new';
                }
            }

            // Count cards by state
            let newCount = 0;
            let learningCount = 0;
            let reviewCount = 0;

            for (const card of this.cards) {
                if (card.state === 'new') {
                    newCount++;
                } else if (card.state === 'learning' || card.state === 'relearning') {
                    learningCount++;
                } else if (card.state === 'review') {
                    reviewCount++;
                }
            }

            this.sessionStats.new_cards = newCount;
            this.sessionStats.learning_cards = learningCount;
            this.sessionStats.review_cards = reviewCount;

            // Update counters
            if (this.els.newCardsCounter) {
                this.els.newCardsCounter.textContent = `Новых: ${newCount}`;
            }
            if (this.els.studiedCardsCounter) {
                this.els.studiedCardsCounter.textContent = `В изучении: ${learningCount}`;
            }
            if (this.els.reviewCardsCounter) {
                this.els.reviewCardsCounter.textContent = `На повтор: ${reviewCount}`;
            }

            // Update UI
            this.els.loadingSpinner.style.display = 'none';
            this.els.flashcardView.style.display = 'block';

            // Show first card
            this.showCard(0);
        } catch (error) {
            console.error('Error during initialization:', error);
            this.els.loadingSpinner.style.display = 'none';
            if (this.els.noCardsMessage) {
                this.els.noCardsMessage.style.display = 'block';
            }
        }
    }

    /**
     * Fetch cards from API (AJAX mode).
     */
    async fetchCards() {
        try {
            let url = this.config.fetchCardsUrl;
            const params = new URLSearchParams();

            // Add extra params from config
            const fp = this.config.fetchCardsParams || {};
            for (const [key, value] of Object.entries(fp)) {
                if (value !== null && value !== undefined) {
                    params.append(key, value);
                }
            }

            // Anti-repeat: exclude recently shown card IDs
            if (this.recentCardIds.length > 0) {
                params.append('exclude_card_ids', this.recentCardIds.join(','));
            }

            const qs = params.toString();
            if (qs) {
                url += (url.includes('?') ? '&' : '?') + qs;
            }

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error('Failed to fetch cards');
            }

            const data = await response.json();

            // Check for daily limit reached
            if (data.status === 'daily_limit_reached') {
                this._showDailyLimitMessage(data.stats);
                this._noCardsMessageShown = true;
                return [];
            }

            if (data.status === 'success' && (!data.items || data.items.length === 0)) {
                const remainingNewCards = (data.stats.new_cards_limit || 0) - (data.stats.new_cards_today || 0);
                const remainingReviews = (data.stats.reviews_limit || 0) - (data.stats.reviews_today || 0);

                if (remainingNewCards > 0 || remainingReviews > 0) {
                    this._showNoCardsInSourceMessage(data.stats);
                } else {
                    this._showNoCardsMessage();
                }
                this._noCardsMessageShown = true;
                return [];
            }

            // Store has_more flags for extra study option
            if (data.stats) {
                this.hasMoreNewCards = data.stats.has_more_new || false;
                this.hasMoreReviewCards = data.stats.has_more_reviews || false;
            }

            // Filter cards with valid translations
            return (data.items || []).filter(card => card.translation && card.translation.trim() !== '');
        } catch (error) {
            console.error('Error fetching cards:', error);
            this._showNoCardsMessage();
            this._noCardsMessageShown = true;
            return [];
        }
    }

    /**
     * Process cards: maintain priority order and spread out same-word cards.
     */
    createAlternatingCards(originalCards) {
        if (!originalCards || originalCards.length === 0) {
            return [];
        }

        const relearning = [];
        const learning = [];
        const review = [];
        const newCards = [];

        for (const card of originalCards) {
            if (card.state === 'relearning') {
                relearning.push(card);
            } else if (card.state === 'learning') {
                learning.push(card);
            } else if (card.is_new) {
                newCards.push(card);
            } else {
                review.push(card);
            }
        }

        return [
            ...this.spreadSameWordCards(this._shuffleArray(relearning)),
            ...this.spreadSameWordCards(this._shuffleArray(learning)),
            ...this.spreadSameWordCards(this._shuffleArray(review)),
            ...this.spreadSameWordCards(this._shuffleArray(newCards))
        ];
    }

    /**
     * Fisher-Yates shuffle.
     */
    _shuffleArray(arr) {
        const result = [...arr];
        for (let i = result.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [result[i], result[j]] = [result[j], result[i]];
        }
        return result;
    }

    /**
     * Spread out cards of the same word so they don't appear consecutively.
     */
    spreadSameWordCards(cards) {
        if (cards.length <= 2) return cards;

        const byWord = {};
        for (const card of cards) {
            if (!byWord[card.word_id]) byWord[card.word_id] = [];
            byWord[card.word_id].push(card);
        }

        const wordIds = Object.keys(byWord);
        if (wordIds.length === cards.length) return cards;

        const result = [];
        let hasMore = true;
        let round = 0;
        const shuffledWordIds = this._shuffleArray(wordIds);

        while (hasMore) {
            hasMore = false;
            for (const wordId of shuffledWordIds) {
                if (byWord[wordId].length > round) {
                    result.push(byWord[wordId][round]);
                    if (byWord[wordId].length > round + 1) {
                        hasMore = true;
                    }
                }
            }
            round++;
        }

        return result;
    }

    /**
     * Display a card at the given index.
     */
    _recountRemaining() {
        // Recount remaining cards ahead in the queue by state (Anki-style)
        let newCount = 0, learningCount = 0, reviewCount = 0;
        for (let i = this.currentCardIndex + 1; i < this.cards.length; i++) {
            const s = this.cards[i].state;
            if (s === 'new') newCount++;
            else if (s === 'learning' || s === 'relearning') learningCount++;
            else if (s === 'review') reviewCount++;
        }
        this.sessionStats.new_cards = newCount;
        this.sessionStats.learning_cards = learningCount;
        this.sessionStats.review_cards = reviewCount;
        if (this.els.newCardsCounter) {
            this.els.newCardsCounter.textContent = `Новых: ${newCount}`;
        }
        if (this.els.studiedCardsCounter) {
            this.els.studiedCardsCounter.textContent = `В изучении: ${learningCount}`;
        }
        if (this.els.reviewCardsCounter) {
            this.els.reviewCardsCounter.textContent = `На повтор: ${reviewCount}`;
        }
    }

    showCard(index) {
        if (!this.cards || this.cards.length === 0) {
            this._showNoCardsMessage();
            return;
        }

        if (index >= this.cards.length) {
            this.completeSession();
            return;
        }

        const card = this.cards[index];
        this.currentCardIndex = index;

        // Update state badge
        this._updateStateDisplay(card);

        // Update progress
        const progress = ((index + 1) / this.cards.length) * 100;
        if (this.els.progressFill) {
            this.els.progressFill.style.width = `${progress}%`;
        }
        if (this.els.cardCounter) {
            this.els.cardCounter.textContent = `Карточка ${index + 1} из ${this.cards.length}`;
        }

        // Reset card state
        if (this.els.cardFront) this.els.cardFront.style.display = 'flex';
        if (this.els.cardBack) this.els.cardBack.style.display = 'none';
        if (this.els.showAnswerBtn) this.els.showAnswerBtn.style.display = 'block';
        if (this.els.hintText) this.els.hintText.classList.remove('visible');

        // Clear previous hint timeout
        if (this.hintTimeout) {
            clearTimeout(this.hintTimeout);
        }

        if (this.els.frontAudioBtn) this.els.frontAudioBtn.hidden = true;
        if (this.els.backAudioBtn) this.els.backAudioBtn.hidden = true;

        // Configure audio
        const hasAudio = card.audio_url !== null && card.audio_url !== undefined;

        // Unit type badge (WORD / PHRASE / PATTERN)
        if (this.els.unitTypeBadge) {
            const unitType = card.unit_type;
            if (unitType) {
                this.els.unitTypeBadge.textContent = unitType.toUpperCase();
                this.els.unitTypeBadge.className = 'fc-unit-type fc-unit-type--' + unitType;
                this.els.unitTypeBadge.style.display = '';
            } else {
                this.els.unitTypeBadge.style.display = 'none';
            }
        }

        // Usage note on back
        if (this.els.cardNote) {
            if (card.note) {
                this.els.cardNote.style.display = '';
                if (this.els.cardNoteText) this.els.cardNoteText.textContent = card.note;
            } else {
                this.els.cardNote.style.display = 'none';
            }
        }

        // Set card content
        if (this.els.frontWord) this.els.frontWord.textContent = card.word;
        if (this.els.backWord) this.els.backWord.textContent = card.word;
        if (this.els.translationText) this.els.translationText.textContent = card.translation;

        // Hint
        const hint = this.formatHint(card.translation);
        if (this.els.hintText) {
            this.els.hintText.textContent = hint;
            this.els.hintText.style.display = hint ? '' : 'none';
        }

        // Leech hint
        if (this.els.leechHint) {
            if (card.is_leech && card.leech_hint) {
                this.els.leechHint.style.display = 'block';
                if (this.els.leechHintText) this.els.leechHintText.textContent = card.leech_hint;
            } else {
                this.els.leechHint.style.display = 'none';
                if (this.els.leechHintText) this.els.leechHintText.textContent = '';
            }
        }

        // Book context (for book-course cards)
        if (this.config.showBookContext && this.els.bookContext) {
            if (card.book_context) {
                this.els.bookContext.style.display = 'block';
                if (this.els.bookContextText) this.els.bookContextText.textContent = card.book_context;
            } else {
                this.els.bookContext.style.display = 'none';
            }
        }

        // Audio setup
        if (hasAudio && this.config.showAudio) {
            if (card.audio_url && this.els.wordAudio) {
                this.els.wordAudio.src = card.audio_url;
            }

            if (card.direction === 'eng-rus') {
                if (this.els.frontAudioBtn) this.els.frontAudioBtn.hidden = false;
                if (this.els.backAudioBtn) this.els.backAudioBtn.hidden = false;

                // Auto-play for eng-rus on front
                if (this.els.wordAudio) {
                    setTimeout(() => {
                        this.els.wordAudio.play().catch(() => {});
                    }, 300);
                }
            } else {
                // rus-eng: no audio on front, show on back
                if (this.els.frontAudioBtn) this.els.frontAudioBtn.hidden = true;
                if (this.els.backAudioBtn) this.els.backAudioBtn.hidden = false;
            }
        } else {
            if (this.els.frontAudioBtn) this.els.frontAudioBtn.hidden = true;
            if (this.els.backAudioBtn) this.els.backAudioBtn.hidden = true;
        }

        // Show hint after 7 seconds
        if (hint) {
            this.hintTimeout = setTimeout(() => {
                if (this.els.hintText) this.els.hintText.classList.add('visible');
            }, 7000);
        }

        // Examples
        if (this.config.showExamples && card.examples) {
            const example = this._extractExampleParts(card.examples);
            if (this.els.exampleText) this.els.exampleText.textContent = example.en;
            if (this.els.exampleTranslation) this.els.exampleTranslation.textContent = example.ru;
            if (this.els.examplesContainer) this.els.examplesContainer.style.display = 'block';
        } else {
            if (this.els.examplesContainer) this.els.examplesContainer.style.display = 'none';
        }
    }

    /**
     * Flip card to reveal the answer side.
     */
    flipCard() {
        if (this.els.cardFront) this.els.cardFront.style.display = 'none';
        if (this.els.cardBack) this.els.cardBack.style.display = 'flex';

        // Clear hint timeout
        if (this.hintTimeout) {
            clearTimeout(this.hintTimeout);
            this.hintTimeout = null;
        }

        // Auto-play audio on answer side (especially for rus-eng)
        const card = this.cards[this.currentCardIndex];
        if (card && card.audio_url && this.config.showAudio && this.els.wordAudio) {
            setTimeout(() => {
                this.els.wordAudio.play().catch(error => {
                    console.log('Audio playback failed:', error);
                });
            }, 300);
        }
    }

    /**
     * Generate hint text from word.
     */
    formatHint(word) {
        if (!word || word.length === 0) return '';

        let targetWord = word;
        if (word.includes(',')) {
            targetWord = word.split(',')[0].trim();
        }

        if (targetWord.length <= 2) {
            return '';
        }

        const firstChar = targetWord.charAt(0).toLowerCase();
        const underscores = '_'.repeat(Math.min(targetWord.length - 1, 8));
        const letterCount = targetWord.length;

        // Russian declension for "буква"
        let letterForm = 'букв';
        const lastDigit = letterCount % 10;

        if (letterCount % 100 >= 11 && letterCount % 100 <= 19) {
            letterForm = 'букв';
        } else if (lastDigit === 1) {
            letterForm = 'буква';
        } else if (lastDigit >= 2 && lastDigit <= 4) {
            letterForm = 'буквы';
        }

        return `Подсказка: ${firstChar}${underscores} (${letterCount} ${letterForm})`;
    }

    /**
     * Rate a card and move to the next.
     */
    async rateCard(rating) {
        if (this._rateInFlight) return;
        if (!this.cards || this.currentCardIndex >= this.cards.length) {
            console.error('Cannot rate card - invalid card index');
            return;
        }
        this._rateInFlight = true;

        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta && csrfMeta.content;
        const card = this.cards[this.currentCardIndex];

        // Track session attempts
        const cardKey = `${card.word_id}_${card.direction}`;
        this.sessionAttempts[cardKey] = (this.sessionAttempts[cardKey] || 0) + 1;

        try {
            const extraParams = {
                deckId: this.config.deckId,
                extraStudy: this.config.extraStudy,
                lessonMode: this.config.lessonMode
            };
            const body = this.config.gradePayload(card, rating, this.config.sessionId, extraParams);

            const response = await fetch(this.config.gradeUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken && { 'X-CSRFToken': csrfToken }),
                },
                body: JSON.stringify(body),
            });

            const contentType = response.headers.get('content-type');

            if (!contentType || !contentType.includes('application/json')) {
                const text = await response.text();
                console.error('Server error:', response.status, 'Content-Type:', contentType, 'Body:', text.substring(0, 500));
                if (this.config.lessonMode) {
                    // In lesson mode, session expiry should not block progress — navigate back cleanly
                    window.location.href = this.config.backUrl;
                } else {
                    alert('Сессия истекла. Перезагрузите страницу.');
                    window.location.reload();
                }
                return;
            }

            const data = await response.json();

            if (!response.ok) {
                console.error('Server error:', response.status, 'Content-Type:', contentType, 'Body:', data);

                if (response.status === 429 && data.error === 'daily_limit_exceeded') {
                    // In lesson mode the backend should never return 429, but if it does, continue silently
                    if (!this.config.lessonMode) {
                        alert('Дневной лимит новых карточек достигнут. Эта карточка не засчитана.');
                    }
                    this.showCard(this.currentCardIndex + 1);
                    return;
                }

                if (response.status === 400 || response.status === 401 || response.status === 403) {
                    if (this.config.lessonMode) {
                        window.location.href = this.config.backUrl;
                    } else {
                        alert('Сессия истекла. Перезагрузите страницу.');
                        window.location.reload();
                    }
                    return;
                }

                alert(data.message || 'Произошла ошибка. Попробуйте ещё раз.');
                return;
            }

            // Anti-repeat: track card_id
            if (data.card_id) {
                this.recentCardIds.push(data.card_id);
                while (this.recentCardIds.length > this.RECENT_CARDS_LIMIT) {
                    this.recentCardIds.shift();
                }
            }

            // Check daily limit exceeded
            if (!data.success && data.error === 'daily_limit_exceeded') {
                if (!this.config.lessonMode) {
                    alert('Дневной лимит новых карточек достигнут. Эта карточка не засчитана.');
                }
                this.showCard(this.currentCardIndex + 1);
                return;
            }

            // Handle buried cards
            if (data.is_buried) {
                console.log(`Card ${data.card_id} buried after ${this.MAX_SESSION_ATTEMPTS} attempts`);
            }

            // Handle requeue
            let shouldRequeue = false;
            let requeuePosition = null;

            if (data.requeue_position !== null && data.requeue_position !== undefined && !data.is_buried) {
                if (this.sessionAttempts[cardKey] < this.MAX_SESSION_ATTEMPTS) {
                    shouldRequeue = true;
                    requeuePosition = data.requeue_position;
                }
            }

            if (shouldRequeue && requeuePosition !== null) {
                const oldState = card.state;
                const newState = data.state || card.state;

                const cardCopy = {
                    ...card,
                    isRequeue: true,
                    state: newState,
                    step_index: data.step_index !== undefined ? data.step_index : card.step_index,
                    lapses: data.lapses !== undefined ? data.lapses : card.lapses
                };
                const insertAt = Math.min(this.currentCardIndex + requeuePosition, this.cards.length);
                this.cards.splice(insertAt, 0, cardCopy);
                console.log(`Card requeued at position +${requeuePosition}, state: ${newState} (session attempt ${this.sessionAttempts[cardKey]})`);

                // Update counters for state transitions
                if (oldState === 'new' && (newState === 'learning' || newState === 'relearning')) {
                    this.sessionStats.learning_cards++;
                    if (this.els.studiedCardsCounter) {
                        this.els.studiedCardsCounter.textContent = `В изучении: ${this.sessionStats.learning_cards}`;
                    }
                } else if (oldState === 'review' && newState === 'relearning') {
                    this.sessionStats.learning_cards++;
                    if (this.els.studiedCardsCounter) {
                        this.els.studiedCardsCounter.textContent = `В изучении: ${this.sessionStats.learning_cards}`;
                    }
                }
            }

            // Update session stats
            this.sessionStats.total++;

            // Recount remaining cards in queue (like Anki)
            this._recountRemaining();

            // Move to next card
            this.showCard(this.currentCardIndex + 1);

        } catch (error) {
            console.error('Error rating card:', error);
            alert('Не удалось сохранить оценку. Попробуйте ещё раз.');
        } finally {
            this._rateInFlight = false;
        }
    }

    /**
     * Complete the study session.
     */
    async completeSession() {
        // If no completeUrl, show celebration with local stats
        if (!this.config.completeUrl) {
            this._showCelebration({
                words_studied: this.sessionStats.total,
                correct: this.sessionStats.total - this.sessionStats.incorrect,
                percentage: this.sessionStats.total > 0
                    ? Math.round(((this.sessionStats.total - this.sessionStats.incorrect) / this.sessionStats.total) * 100)
                    : 0
            }, 0, 1, 0, 0);

            // Mark lesson complete if URL provided
            if (this.config.markLessonCompleteUrl) {
                this._markLessonComplete();
            }

            // Callback
            if (this.config.onComplete) {
                this.config.onComplete({
                    stats: this.sessionStats
                });
            }
            return;
        }

        try {
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const csrfToken = csrfMeta && csrfMeta.content;

            const body = this.config.completePayload
                ? this.config.completePayload(this.config.sessionId, this.sessionStats)
                : { session_id: this.config.sessionId };

            const response = await fetch(this.config.completeUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken && { 'X-CSRFToken': csrfToken })
                },
                body: JSON.stringify(body),
            });

            const data = await response.json();

            if (data.success) {
                const stats = data.stats || {};
                this._showCelebration(
                    stats,
                    data.xp_earned || 0,
                    data.level || 1,
                    data.total_xp || 0,
                    data.streak || 0
                );

                // Show extra study button if more cards available
                if (this.hasMoreNewCards || this.hasMoreReviewCards) {
                    const extraLink = document.getElementById('session-extra-study-link');
                    if (extraLink) {
                        extraLink.style.display = 'inline-flex';
                    }
                }

                // Mark lesson complete if URL provided
                if (this.config.markLessonCompleteUrl) {
                    this._markLessonComplete();
                }

                // Callback
                if (this.config.onComplete) {
                    this.config.onComplete(data);
                }

                // Notify daily plan module
                document.dispatchEvent(new Event('dailyPlanStepComplete'));
            }
        } catch (error) {
            console.error('Error completing session:', error);
            window.location.href = this.config.backUrl;
        }
    }

    /**
     * Mark lesson as complete via API.
     */
    async _markLessonComplete() {
        try {
            const csrfMeta = document.querySelector('meta[name="csrf-token"]');
            const csrfToken = csrfMeta && csrfMeta.content;

            await fetch(this.config.markLessonCompleteUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken && { 'X-CSRFToken': csrfToken })
                },
                body: JSON.stringify({}),
            });
        } catch (error) {
            console.error('Error marking lesson complete:', error);
        }
    }

    /**
     * Show celebration/completion screen.
     */
    _showCelebration(stats, xpEarned, level, totalXp, streak) {
        // Hide progress bar and cards
        if (this.els.progressSection) this.els.progressSection.style.display = 'none';
        if (this.els.cardFront) this.els.cardFront.style.display = 'none';
        if (this.els.cardBack) this.els.cardBack.style.display = 'none';
        if (this.els.noCardsMessage) this.els.noCardsMessage.style.display = 'none';
        if (this.els.dailyLimitMessage) this.els.dailyLimitMessage.style.display = 'none';
        const noCardsInSource = document.getElementById('no-cards-in-source-message');
        if (noCardsInSource) noCardsInSource.style.display = 'none';

        // Show completion screen
        if (this.els.flashcardView) this.els.flashcardView.style.display = 'block';
        if (this.els.sessionComplete) this.els.sessionComplete.style.display = 'flex';

        // Set random completion message
        const titleEl = document.getElementById('celebration-title');
        if (titleEl) {
            titleEl.textContent = this._getRandomCompletionMessage();
        }

        // Get stats values
        const wordsStudied = stats.words_studied || 0;
        const correct = stats.correct || 0;
        const percentage = stats.percentage || 0;

        // Animate stats
        this.animateValue('stats-words', 0, wordsStudied, 800);
        this.animateValue('stats-correct', 0, correct, 800);
        this.animateValue('stats-score', 0, percentage, 1000);
        this.animateValue('xp-earned-amount', 0, xpEarned, 1200);

        // Animate accuracy ring
        setTimeout(() => {
            const accuracyRing = document.querySelector('.accuracy-progress');
            if (accuracyRing) {
                const circumference = 213.6;
                const offset = circumference - (percentage / 100) * circumference;
                accuracyRing.style.strokeDashoffset = offset;
            }
        }, 300);

        // Update level
        const levelEl = document.getElementById('current-level');
        if (levelEl) levelEl.textContent = level;
        const totalXpEl = document.getElementById('total-xp');
        if (totalXpEl) totalXpEl.textContent = totalXp;

        // Show streak status
        if (streak > 0) {
            const streakEl = document.getElementById('streak-status');
            const streakDaysEl = document.getElementById('streak-days');
            if (streakEl && streakDaysEl) {
                streakDaysEl.textContent = streak;
                streakEl.style.display = 'flex';
            }
        }

        // Update action buttons
        const continueBtn = document.getElementById('fc-continue-btn');
        if (continueBtn) {
            continueBtn.href = this.config.onCompleteUrl;
            continueBtn.textContent = this.config.onCompleteText;
        }

        // Launch confetti
        this.launchConfetti();
    }

    /**
     * Confetti animation.
     */
    launchConfetti() {
        const canvas = document.getElementById('confetti-canvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        canvas.width = canvas.offsetWidth;
        canvas.height = canvas.offsetHeight;

        const particles = [];
        const colors = ['#10b981', '#f59e0b', '#3b82f6', '#ec4899', '#8b5cf6', '#06b6d4'];

        for (let i = 0; i < 80; i++) {
            particles.push({
                x: canvas.width / 2,
                y: canvas.height / 2,
                vx: (Math.random() - 0.5) * 15,
                vy: (Math.random() - 0.5) * 15 - 5,
                color: colors[Math.floor(Math.random() * colors.length)],
                size: Math.random() * 8 + 4,
                rotation: Math.random() * 360,
                rotationSpeed: (Math.random() - 0.5) * 10,
                gravity: 0.2,
                friction: 0.99,
                opacity: 1
            });
        }

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            let activeParticles = 0;
            particles.forEach(p => {
                if (p.opacity <= 0) return;
                activeParticles++;

                p.vy += p.gravity;
                p.vx *= p.friction;
                p.vy *= p.friction;
                p.x += p.vx;
                p.y += p.vy;
                p.rotation += p.rotationSpeed;

                if (p.y > canvas.height * 0.8) {
                    p.opacity -= 0.02;
                }

                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate(p.rotation * Math.PI / 180);
                ctx.globalAlpha = p.opacity;
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
                ctx.restore();
            });

            if (activeParticles > 0) {
                requestAnimationFrame(animate);
            } else {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }

        animate();
    }

    /**
     * Animate number counting.
     */
    animateValue(elementId, start, end, duration) {
        const el = document.getElementById(elementId);
        if (!el) return;

        const range = end - start;
        const startTime = performance.now();

        function update(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeOut = 1 - Math.pow(1 - progress, 3);
            const current = Math.round(start + range * easeOut);
            el.textContent = current;

            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }

        requestAnimationFrame(update);
    }

    // ========================================
    // Private helper methods
    // ========================================

    _getRandomCompletionMessage() {
        return this.completionMessages[Math.floor(Math.random() * this.completionMessages.length)];
    }

    _updateStateDisplay(card) {
        const state = card.state || 'new';
        const lapses = card.lapses || 0;

        if (this.els.stateBadge) {
            const config = this.STATE_CONFIG[state] || this.STATE_CONFIG['new'];
            this.els.stateBadge.textContent = config.label;
            this.els.stateBadge.className = 'badge ' + config.class;
        }

        if (this.els.lapsesBadge) {
            if (lapses > 0) {
                this.els.lapsesBadge.textContent = `Провалов: ${lapses}`;
                this.els.lapsesBadge.style.display = 'inline-block';
            } else {
                this.els.lapsesBadge.style.display = 'none';
            }
        }
    }

    _extractExampleParts(examples) {
        if (!examples) return { en: '', ru: '' };

        const withNewlines = examples.replace(/<br\s*\/?>/gi, '\n');
        const cleanedExamples = withNewlines.replace(/<[^>]*>/g, '');

        let lines = cleanedExamples.split('\n').filter(line => line.trim() !== '');

        if (lines.length >= 2) {
            return { en: lines[0].trim(), ru: lines[1].trim() };
        }

        lines = cleanedExamples.split(/\n\s*-\s*/).filter(line => line.trim() !== '');
        if (lines.length >= 2) {
            return { en: lines[0].trim(), ru: lines[1].trim() };
        }

        const hasCyrillic = /[А-Яа-я]/.test(cleanedExamples);
        const hasLatin = /[A-Za-z]/.test(cleanedExamples);

        if (hasCyrillic && hasLatin) {
            const parts = cleanedExamples.split(/[;.]\s*/).filter(part => part.trim() !== '');
            const enPart = parts.find(part => /[A-Za-z]/.test(part)) || '';
            const ruPart = parts.find(part => /[А-Яа-я]/.test(part)) || '';
            return { en: enPart.trim(), ru: ruPart.trim() };
        }

        return { en: cleanedExamples.trim(), ru: '' };
    }

    _showNoCardsMessage() {
        if (this.els.loadingSpinner) this.els.loadingSpinner.style.display = 'none';
        if (this.els.flashcardView) this.els.flashcardView.style.display = 'block';
        if (this.els.noCardsMessage) this.els.noCardsMessage.style.display = 'block';
    }

    _showDailyLimitMessage(stats) {
        if (this.els.loadingSpinner) this.els.loadingSpinner.style.display = 'none';
        if (this.els.flashcardView) this.els.flashcardView.style.display = 'block';
        if (this.els.cardFront) this.els.cardFront.style.display = 'none';
        if (this.els.cardBack) this.els.cardBack.style.display = 'none';
        if (this.els.noCardsMessage) this.els.noCardsMessage.style.display = 'none';
        if (this.els.sessionComplete) this.els.sessionComplete.style.display = 'none';

        if (this.els.newCardsStats) {
            this.els.newCardsStats.textContent = `${stats.new_cards_today} / ${stats.new_cards_limit}`;
        }
        if (this.els.reviewsStats) {
            this.els.reviewsStats.textContent = `${stats.reviews_today} / ${stats.reviews_limit}`;
        }

        if (this.els.dailyLimitMessage) this.els.dailyLimitMessage.style.display = 'block';
    }

    _showNoCardsInSourceMessage(stats) {
        if (this.els.loadingSpinner) this.els.loadingSpinner.style.display = 'none';
        if (this.els.cardFront) this.els.cardFront.style.display = 'none';
        if (this.els.cardBack) this.els.cardBack.style.display = 'none';
        if (this.els.noCardsMessage) this.els.noCardsMessage.style.display = 'none';
        if (this.els.sessionComplete) this.els.sessionComplete.style.display = 'none';
        if (this.els.dailyLimitMessage) this.els.dailyLimitMessage.style.display = 'none';

        if (this.els.progressSection) this.els.progressSection.style.display = 'none';
        if (this.els.flashcardView) this.els.flashcardView.style.display = 'block';

        const noCardsInSourceMessage = document.getElementById('no-cards-in-source-message');
        if (!noCardsInSourceMessage) return;

        const title = document.getElementById('no-cards-title');
        if (title) {
            title.textContent = this._getRandomCompletionMessage();
        }

        const sessionNewCount = document.getElementById('session-new-count');
        const sessionLearningCount = document.getElementById('session-learning-count');
        const sessionReviewCount = document.getElementById('session-review-count');

        if (sessionNewCount) sessionNewCount.textContent = stats.new_cards_today || 0;
        if (sessionLearningCount) sessionLearningCount.textContent = this.sessionStats.learning_cards || 0;
        if (sessionReviewCount) sessionReviewCount.textContent = stats.reviews_today || 0;

        noCardsInSourceMessage.style.display = 'block';
    }
}
