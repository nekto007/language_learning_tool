// Variables to store session data
let cards = []; // All cards for the session
let currentCardIndex = 0; // Current card index
let cardsToReview = []; // Cards to be reviewed again in this session
let againCardIds = new Set(); // Track cards that were marked "Again"
let reviewedCardIds = new Set(); // Keep track of cards we've reviewed in this session
let checkForNewDueCardsInterval = null; // Interval for checking new due cards
let sessionStats = {
    again: 0,  // Card needs to be relearned
    hard: 0,   // Recalled with difficulty
    good: 0,   // Normal recall
    easy: 0    // Recalled easily
};
let audioElement = new Audio();
let isAnswerShown = false; // Track if answer is currently shown

// Constants for same-session learning
const AGAIN_DELAY_MINUTES = 10; // Delay before showing "Again" cards (10 minutes)

const translations = {
    'ru': {
        'again': 'Снова',
        'hard': 'Трудно',
        'good': 'Хорошо',
        'easy': 'Легко',
        'showAnswer': 'Показать ответ',
        'listen': 'Прослушать'
    },
    'en': {
        'again': 'Again',
        'hard': 'Hard',
        'good': 'Good',
        'easy': 'Easy',
        'showAnswer': 'Show Answer',
        'listen': 'Listen'
    }
};

/**
 * Add styles to the page
 */
function addStyles() {
    // Create link to external CSS file
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/css/flashcard-styles.css';
    document.head.appendChild(link);

    // Fallback inline styles in case the CSS file doesn't load
    const style = document.createElement('style');
    style.textContent = `
        .card { box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1); }
        .word-text { font-size: 2.5rem; font-weight: 600; color: #333; }
        #russianWord { font-size: 2rem; color: #e74c3c !important; font-weight: 500; }
        #exampleText { color: #495057 !important; font-size: 1.1rem; line-height: 1.6; }
        .difficulty-btn { transition: transform 0.2s ease; min-width: 80px; border-radius: 8px; }
        .difficulty-btn:hover { transform: translateY(-3px); }
        .difficulty-btn.active-response { transform: scale(0.95); }
    `;
    document.head.appendChild(style);
}

/**
 * Get user's browser language preference
 * @returns {string} Language code (en or ru)
 */
function getBrowserLanguage() {
    // Get user's preferred language
    const userLang = navigator.language || navigator.userLanguage;
    // Check if it starts with 'ru'
    if (userLang.startsWith('ru')) {
        return 'ru';
    }
    // Default to English
    return 'en';
}

/**
 * Apply translations based on browser language
 */
function applyTranslations() {
    const lang = getBrowserLanguage();
    const texts = translations[lang] || translations['en']; // English as fallback

    // Update all elements with data-key attribute
    document.querySelectorAll('[data-key]').forEach(element => {
        const key = element.dataset.key;
        if (texts[key]) {
            element.textContent = texts[key];
        }
    });

    // Update specific elements
    const showAnswerBtn = document.getElementById('showAnswerBtn');
    if (showAnswerBtn) {
        showAnswerBtn.textContent = texts['showAnswer'];
    }

    // Update front audio button
    const playAudioBtn = document.getElementById('playAudioBtn');
    if (playAudioBtn) {
        const icon = playAudioBtn.querySelector('i');
        if (icon) {
            playAudioBtn.innerHTML = '';
            playAudioBtn.appendChild(icon);
            playAudioBtn.appendChild(document.createTextNode(' ' + texts['listen']));
        } else {
            playAudioBtn.textContent = texts['listen'];
        }
    }

    // Update back audio button
    const playAudioBtnBack = document.getElementById('playAudioBtnBack');
    if (playAudioBtnBack) {
        const icon = playAudioBtnBack.querySelector('i');
        if (icon) {
            playAudioBtnBack.innerHTML = '';
            playAudioBtnBack.appendChild(icon);
            playAudioBtnBack.appendChild(document.createTextNode(' ' + texts['listen']));
        } else {
            playAudioBtnBack.textContent = texts['listen'];
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Add styles to the page
    addStyles();

    // Load cards data via AJAX
    applyTranslations();
    loadCardsData();

    // Set up event listeners
    const showAnswerBtn = document.getElementById('showAnswerBtn');
    if (showAnswerBtn) {
        showAnswerBtn.addEventListener('click', showAnswer);
    }

    document.querySelectorAll('.difficulty-btn').forEach(button => {
        button.addEventListener('click', function() {
            const difficulty = this.dataset.difficulty;
            processAnswer(difficulty);
        });
    });

    // Set up audio button event listeners
    const playAudioBtn = document.getElementById('playAudioBtn');
    const playAudioBtnBack = document.getElementById('playAudioBtnBack');

    if (playAudioBtn) {
        playAudioBtn.addEventListener('click', playAudio);
    }

    if (playAudioBtnBack) {
        playAudioBtnBack.addEventListener('click', playAudio);
    }

    // Pre-set audio to allow user interaction to trigger it later
    audioElement.preload = 'auto';

    // Exit confirmation
    const exitBtn = document.getElementById('exitBtn');
    if (exitBtn) {
        exitBtn.addEventListener('click', function(e) {
            if (currentCardIndex > 0 && currentCardIndex < cards.length) {
                if (!confirm('Are you sure you want to exit? Your session progress will be lost.')) {
                    e.preventDefault();
                }
            }
        });
    }

    // Set up keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        if (!isAnswerShown) {
            // Front of the card is shown
            if (e.key === ' ' || e.key === 'Enter') {
                // Space or Enter to show answer
                e.preventDefault();
                showAnswer();
            }
        } else {
            // Back of the card is shown (keyboard shortcuts for difficulty levels)
            if (e.key === '1' || e.key === 'a') {
                // 1 or a for "again"
                processAnswer('again');
            } else if (e.key === '2' || e.key === 'h') {
                // 2 or h for "hard"
                processAnswer('hard');
            } else if (e.key === '3' || e.key === 'g') {
                // 3 or g for "good"
                processAnswer('good');
            } else if (e.key === '4' || e.key === 'e') {
                // 4 or e for "easy"
                processAnswer('easy');
            }
        }
    });

    // Initialize check for new due cards - every minute check if more cards have become due
    checkForNewDueCardsInterval = setInterval(checkForNewDueCards, 60000);
});

/**
 * Load cards data via AJAX
 */
function loadCardsData() {
    const sessionIdElement = document.getElementById('sessionId');
    if (!sessionIdElement) {
        console.error('Session ID element not found');
        return;
    }

    const sessionId = sessionIdElement.value;

    fetch(`/srs/review/data/${sessionId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Server returned error: ' + response.status);
            }
            return response.json();
        })
        .then(data => {
            cards = data;
            console.log("Successfully loaded", cards.length, "cards");

            // Hide loading indicator
            const loadingContainer = document.getElementById('loadingContainer');
            if (loadingContainer) {
                loadingContainer.style.display = 'none';
            }

            // Show card container
            const cardContainer = document.getElementById('cardContainer');
            if (cardContainer) {
                cardContainer.style.display = 'block';
            }

            // Start with the first card
            if (cards.length > 0) {
                showCard(0);
            } else {
                console.error("No cards available for review");
                const deckIdElement = document.getElementById('deckId');
                if (deckIdElement) {
                    window.location.href = `/srs/decks/${deckIdElement.value}`;
                } else {
                    window.location.href = '/srs/decks/';
                }
            }
        })
        .catch(error => {
            console.error('Error loading cards data:', error);
            const loadingContainer = document.getElementById('loadingContainer');
            const deckIdElement = document.getElementById('deckId');

            if (loadingContainer && deckIdElement) {
                loadingContainer.innerHTML = `
                    <div class="alert alert-danger" role="alert">
                        <h4 class="alert-heading">Error loading data</h4>
                        <p>${error.message}</p>
                        <hr>
                        <p class="mb-0">
                            <a href="/srs/decks/${deckIdElement.value}" class="btn btn-outline-danger">
                                Return to deck
                            </a>
                        </p>
                    </div>
                `;
            }
        });
}

/**
 * Format examples with proper styling
 * @param {string} examples - HTML string with examples
 * @returns {string} Properly formatted HTML
 */
function formatExamples(examples) {
    if (!examples) return '';

    // Check if the examples already have HTML structure
    if (examples.includes('<div>') || examples.includes('<p>')) {
        return examples;
    }

    // Split by new lines or periods to identify English and Russian parts
    const parts = examples.split(/\n|\.(?=\s|$)/g).filter(part => part.trim().length > 0);

    let formattedHtml = '';

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i].trim();
        if (!part) continue;

        // Check if this part contains Cyrillic characters
        const hasCyrillic = /[А-Яа-я]/.test(part);

        if (hasCyrillic) {
            formattedHtml += `<p class="example-russian">${part}.</p>`;
        } else {
            formattedHtml += `<p class="example-english">${part}.</p>`;
        }
    }

    return formattedHtml;
}

/**
 * Show current card
 * @param {number} index - Index of the card to show
 */
function showCard(index) {
    if (index >= cards.length) {
        // Check if we have cards marked with "Again" to review
        if (cardsToReview.length > 0) {
            processReviewQueue();
            return;
        }

        // No more cards, show complete modal
        showSessionComplete();
        return;
    }

    const card = cards[index];

    // Update progress
    currentCardIndex = index;
    updateProgress();

    // Reset card state
    const cardFront = document.getElementById('cardFront');
    const cardBack = document.getElementById('cardBack');

    if (cardFront && cardBack) {
        // Add transition class
        cardFront.classList.add('hiding');
        cardBack.classList.add('hiding');

        // After a brief delay, update content and show
        setTimeout(() => {
            cardFront.style.display = 'block';
            cardBack.style.display = 'none';
            isAnswerShown = false;

            // Set card content - for English word (just text)
            const englishWord = document.getElementById('englishWord');
            const englishWordBack = document.getElementById('englishWordBack');

            if (englishWord) {
                englishWord.textContent = card.english_word || '';
            }

            if (englishWordBack) {
                englishWordBack.textContent = card.english_word || '';
            }

            // For Russian translation - just text
            const russianWord = document.getElementById('russianWord');
            if (russianWord) {
                russianWord.textContent = card.russian_word || 'No translation available';
            }

            // Process example sentences on the back of the card
            const exampleContainer = document.getElementById('exampleContainer');
            const exampleText = document.getElementById('exampleText');

            if (exampleContainer && exampleText && card.sentences) {
                // Format the examples with proper styling
                exampleText.innerHTML = formatExamples(card.sentences);
                exampleContainer.style.display = 'block';
            } else if (exampleContainer) {
                exampleContainer.style.display = 'none';
            }

            // Remove transition class after content is updated
            cardFront.classList.remove('hiding');
            cardBack.classList.remove('hiding');
        }, 150);

        // Handle audio buttons - MODIFIED CODE
        const playAudioBtn = document.getElementById('playAudioBtn');
        const playAudioBtnBack = document.getElementById('playAudioBtnBack');

        if ((playAudioBtn || playAudioBtnBack) && card.get_download === 1) {
            // Display both audio buttons if audio is available
            if (playAudioBtn) {
                playAudioBtn.style.display = 'inline-block';
                // Update button appearance to highlight it
                playAudioBtn.classList.add('btn-primary');
                playAudioBtn.classList.remove('btn-outline-primary');
            }

            if (playAudioBtnBack) {
                playAudioBtnBack.style.display = 'inline-block';
                // Update button appearance to highlight it
                playAudioBtnBack.classList.add('btn-primary');
                playAudioBtnBack.classList.remove('btn-outline-primary');
            }

            // Clean the word for filename (lowercase, replace spaces with underscores)
            const cleanWord = card.english_word.toLowerCase().replace(/ /g, '_');

            // Set up audio element
            audioElement.src = `/static/media/pronunciation_en_${cleanWord}.mp3`;

            // Preload audio but don't auto-play
            audioElement.load();

            // Remove auto-play code
        } else {
            // Hide both audio buttons if no audio is available
            if (playAudioBtn) playAudioBtn.style.display = 'none';
            if (playAudioBtnBack) playAudioBtnBack.style.display = 'none';
        }
    }

    // Add animation class for smooth transition
    const cardContainer = document.getElementById('cardContainer');
    if (cardContainer) {
        cardContainer.classList.add('card-transition');
        setTimeout(() => {
            cardContainer.classList.remove('card-transition');
        }, 300);
    }
}

/**
 * Show answer for current card
 */
function showAnswer() {
    const cardFront = document.getElementById('cardFront');
    const cardBack = document.getElementById('cardBack');

    if (cardFront && cardBack) {
        // Add transition class for smooth fade
        cardFront.classList.add('hiding');

        // After short transition
        setTimeout(() => {
            cardFront.style.display = 'none';
            cardBack.style.display = 'block';

            // Remove transition class from back side after a short delay
            setTimeout(() => {
                cardBack.classList.remove('hiding');
            }, 50);

            isAnswerShown = true;

            // Focus the Good button as a reasonable default
            const goodBtn = document.querySelector('.difficulty-btn[data-difficulty="good"]');
            if (goodBtn) {
                goodBtn.focus();
            }
        }, 150);
    }
}

/**
 * Play audio for current word
 */

let audioState = {
    isPlaying: false,
    buttonElement: null,
    originalButtonText: '',
    timer: null
};


function playAudio() {
    // Если уже воспроизводится, просто остановим
    if (audioState.isPlaying) {
        audioElement.pause();
        resetAudioButton();
        return;
    }

    // Определение активной кнопки
    const frontButton = document.getElementById('playAudioBtn');
    const backButton = document.getElementById('playAudioBtnBack');
    const activeButton = (frontButton && frontButton.offsetParent !== null) ? frontButton : backButton;

    if (!activeButton) return;

    // Сохраняем исходное состояние
    audioState.buttonElement = activeButton;
    audioState.originalButtonText = activeButton.innerHTML;
    audioState.isPlaying = true;

    // Показываем состояние загрузки
    activeButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    activeButton.disabled = true;

    // Установка простого таймера безопасности
    if (audioState.timer) clearTimeout(audioState.timer);
    audioState.timer = setTimeout(resetAudioButton, 5000);

    // Подготовка аудио элемента
    audioElement.pause();

    // Очистка всех старых обработчиков
    audioElement.onloadeddata = null;
    audioElement.onplay = null;
    audioElement.onended = null;
    audioElement.onpause = null;
    audioElement.onerror = null;

    // Устанавливаем новые обработчики
    audioElement.onloadeddata = handleAudioLoaded;
    audioElement.onplay = handleAudioPlay;
    audioElement.onended = handleAudioEnded;
    audioElement.onpause = handleAudioPause;
    audioElement.onerror = handleAudioError;

    // Попытка воспроизведения
    try {
        audioElement.currentTime = 0; // Сброс позиции
        const playPromise = audioElement.play();

        // Современные браузеры возвращают Promise
        if (playPromise !== undefined) {
            playPromise
                .then(() => {
                    console.log("Audio playback started successfully");
                })
                .catch(error => {
                    console.error("Audio playback failed:", error);
                    handleAudioError(error);
                });
        }
    } catch (e) {
        console.error("Exception during audio playback:", e);
        handleAudioError(e);
    }
}


/**
 * Process user's answer
 * @param {string} difficulty - The difficulty level ('again', 'hard', 'good', 'easy')
 */
function playAudio() {
    // Получаем активную кнопку
    const frontButton = document.getElementById('playAudioBtn');
    const backButton = document.getElementById('playAudioBtnBack');
    const activeButton = (frontButton && frontButton.offsetParent !== null) ? frontButton : backButton;

    if (!activeButton) return;

    // Сохраняем оригинальный текст
    const originalText = activeButton.innerHTML;

    // Показываем состояние загрузки
    activeButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    activeButton.disabled = true;

    // Простой сброс кнопки через 3 секунды на случай любых проблем
    setTimeout(() => {
        activeButton.innerHTML = originalText;
        activeButton.disabled = false;
    }, 3000);

    // Пробуем воспроизвести аудио
    try {
        audioElement.play()
            .then(() => {
                // Успешное воспроизведение
                activeButton.innerHTML = '<i class="fas fa-volume-up"></i> Playing';
            })
            .catch(error => {
                // Сбрасываем кнопку при ошибке
                activeButton.innerHTML = originalText;
                activeButton.disabled = false;
                console.error('Audio playback error:', error);
            });
    } catch (e) {
        // Сбрасываем кнопку при исключении
        activeButton.innerHTML = originalText;
        activeButton.disabled = false;
        console.error('Exception during playback:', e);
    }
}

// Очищаем все обработчики событий у аудио элемента
audioElement.onloadeddata = null;
audioElement.onplay = null;
audioElement.onended = null;
audioElement.onpause = null;
audioElement.onerror = null;

// Устанавливаем только самый необходимый обработчик
audioElement.onended = function() {
    // Находим активную кнопку при завершении воспроизведения
    const frontButton = document.getElementById('playAudioBtn');
    const backButton = document.getElementById('playAudioBtnBack');
    const activeButton = (frontButton && frontButton.offsetParent !== null) ? frontButton : backButton;

    if (activeButton) {
        // Возвращаем исходный текст
        if (activeButton.classList.contains('front-button')) {
            activeButton.innerHTML = '<i class="fas fa-volume-up"></i> ' + (translations[getBrowserLanguage()] || translations['en'])['listen'];
        } else {
            activeButton.innerHTML = '<i class="fas fa-volume-up"></i> ' + (translations[getBrowserLanguage()] || translations['en'])['listen'];
        }
        activeButton.disabled = false;
    }
};

// Очистим обработчики на кнопках и установим новые
function setupAudioButtons() {
    const frontButton = document.getElementById('playAudioBtn');
    const backButton = document.getElementById('playAudioBtnBack');

    if (frontButton) {
        // Удаляем все предыдущие обработчики
        const newFrontButton = frontButton.cloneNode(true);
        newFrontButton.classList.add('front-button');
        frontButton.parentNode.replaceChild(newFrontButton, frontButton);
        newFrontButton.addEventListener('click', playAudio);
    }

    if (backButton) {
        // Удаляем все предыдущие обработчики
        const newBackButton = backButton.cloneNode(true);
        newBackButton.classList.add('back-button');
        backButton.parentNode.replaceChild(newBackButton, backButton);
        newBackButton.addEventListener('click', playAudio);
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', setupAudioButtons);

// Вызываем сразу же для текущей страницы
setupAudioButtons();

/**
 * Determine and show the next card
 */
function goToNextCard() {
    currentCardIndex++;

    // Check if we've gone through all original cards
    if (currentCardIndex >= cards.length) {
        // If we have cards to review again, process them
        if (cardsToReview.length > 0) {
            processReviewQueue();
        } else {
            // No more cards to review, show completion
            showSessionComplete();
        }
    } else {
        // Show the next card from the original deck
        showCard(currentCardIndex);
    }
}

/**
 * Process cards marked for review again in this session
 */
function processReviewQueue() {
    // Current time
    const now = new Date();

    // Filter cards that are due for review (passed the delay time)
    const dueCards = cardsToReview.filter(card => card.reviewAfter <= now);

    // Keep the rest for later
    cardsToReview = cardsToReview.filter(card => card.reviewAfter > now);

    if (dueCards.length > 0) {
        // Add due cards back to the main deck
        cards = cards.concat(dueCards);

        // Show a message that we're reviewing failed cards
        const loadingContainer = document.getElementById('loadingContainer');
        const cardContainer = document.getElementById('cardContainer');

        if (loadingContainer && cardContainer) {
            loadingContainer.style.display = 'block';
            cardContainer.style.display = 'none';

            loadingContainer.innerHTML = `
                <div class="alert alert-info" role="alert">
                    <h4 class="alert-heading">Reviewing Failed Cards</h4>
                    <p>Now we'll review the ${dueCards.length} card(s) you marked with "Again".</p>
                    <hr>
                    <div class="text-center">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                    </div>
                </div>
            `;

            // Show the first review card after a brief pause
            setTimeout(() => {
                loadingContainer.style.display = 'none';
                cardContainer.style.display = 'block';
                showCard(currentCardIndex);
            }, 2000); // 2-second pause to show the message
        }
    } else if (cardsToReview.length > 0) {
        // We have cards to review but they're not due yet, set a timer
        const nextDueTime = Math.min(...cardsToReview.map(c => c.reviewAfter.getTime()));
        const waitTime = nextDueTime - now.getTime();

        // Show waiting message
        const loadingContainer = document.getElementById('loadingContainer');
        const cardContainer = document.getElementById('cardContainer');

        if (loadingContainer && cardContainer) {
            loadingContainer.style.display = 'block';
            cardContainer.style.display = 'none';

            const minutes = Math.ceil(waitTime / 60000);
            loadingContainer.innerHTML = `
                <div class="alert alert-info" role="alert">
                    <h4 class="alert-heading">Short Break</h4>
                    <p>Wait ${minutes} minute(s) before reviewing cards marked with "Again".</p>
                    <hr>
                    <div class="progress" style="height: 20px;">
                        <div id="waitProgressBar" class="progress-bar progress-bar-striped progress-bar-animated" 
                             role="progressbar" style="width: 0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
                    </div>
                    <p class="mt-2 text-center" id="waitTimeRemaining">${minutes}:00 remaining</p>
                    <div class="text-center mt-3">
                        <button class="btn btn-sm btn-primary" id="skipWaitBtn">Skip Wait Time</button>
                    </div>
                </div>
            `;

            // Add skip button functionality
            const skipWaitBtn = document.getElementById('skipWaitBtn');
            if (skipWaitBtn) {
                skipWaitBtn.addEventListener('click', function() {
                    clearInterval(waitInterval);
                    // Move all cards to due immediately
                    cardsToReview.forEach(card => card.reviewAfter = new Date());
                    processReviewQueue();
                });
            }

            // Update progress bar every second
            let elapsedMs = 0;
            const waitInterval = setInterval(() => {
                elapsedMs += 1000;
                const progress = Math.min(100, (elapsedMs / waitTime) * 100);

                const waitProgressBar = document.getElementById('waitProgressBar');
                if (waitProgressBar) {
                    waitProgressBar.style.width = `${progress}%`;
                }

                // Update remaining time
                const remainingMs = waitTime - elapsedMs;
                const waitTimeRemaining = document.getElementById('waitTimeRemaining');

                if (remainingMs <= 0) {
                    clearInterval(waitInterval);
                    processReviewQueue();
                } else if (waitTimeRemaining) {
                    const remainingMinutes = Math.floor(remainingMs / 60000);
                    const remainingSeconds = Math.floor((remainingMs % 60000) / 1000);
                    waitTimeRemaining.textContent =
                        `${remainingMinutes}:${remainingSeconds.toString().padStart(2, '0')} remaining`;
                }
            }, 1000);
        }
    } else {
        // No more cards to review
        showSessionComplete();
    }
}

/**
 * Update progress indicators
 */
function updateProgress() {
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const remainingCards = document.getElementById('remainingCards');

    if (!progressBar || !progressText || !remainingCards) {
        return;
    }

    const totalCards = cards.length;
    const progress = totalCards > 0 ? (currentCardIndex / totalCards) * 100 : 0;

    progressBar.style.width = `${progress}%`;
    progressBar.setAttribute('aria-valuenow', progress);

    progressText.textContent = `Card ${currentCardIndex + 1} of ${totalCards}`;
    remainingCards.textContent = totalCards - currentCardIndex;
}

/**
 * Show session complete modal with stats
 */
function showSessionComplete() {
    // Before showing completion, check if there are any new due cards
    checkForNewDueCards(true);
}

/**
 * Check for newly due cards from the server
 * @param {boolean} isCompletion - Whether this is called from the completion handler
 */
function checkForNewDueCards(isCompletion = false) {
    const sessionIdElement = document.getElementById('sessionId');
    if (!sessionIdElement) {
        console.error('Session ID element not found');
        if (isCompletion) {
            displaySessionCompleteModal();
        }
        return;
    }

    const sessionId = sessionIdElement.value;

    fetch(`/srs/api/review/refresh-due/${sessionId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Server returned error: ' + response.status);
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.new_due_cards && data.new_due_cards.length > 0) {
                // Filter out cards we've already seen
                const newCards = data.new_due_cards.filter(card => !reviewedCardIds.has(card.id));

                if (newCards.length > 0) {
                    console.log(`Found ${newCards.length} newly due cards to add to the session`);

                    // Add the new cards to our deck
                    cards = cards.concat(newCards);

                    // If we were about to show completion, continue the session instead
                    if (isCompletion) {
                        showContinueSessionMessage(newCards.length);
                    }
                    return;
                }
            }

            // If there are no new cards or we're not in completion mode, proceed normally
            if (isCompletion) {
                displaySessionCompleteModal();
            }
        })
        .catch(error => {
            console.error('Error checking for new due cards:', error);
            // If there's an error and we're in completion mode, show completion anyway
            if (isCompletion) {
                displaySessionCompleteModal();
            }
        });
}

/**
 * Show a message that we're continuing the session with newly due cards
 * @param {number} cardCount - Number of new cards added
 */
function showContinueSessionMessage(cardCount) {
    const loadingContainer = document.getElementById('loadingContainer');
    const cardContainer = document.getElementById('cardContainer');

    if (!loadingContainer || !cardContainer) {
        return;
    }

    loadingContainer.style.display = 'block';
    cardContainer.style.display = 'none';

    loadingContainer.innerHTML = `
        <div class="alert alert-info" role="alert">
            <h4 class="alert-heading">Continuing Review</h4>
            <p>Found ${cardCount} more card(s) that need review.</p>
            <hr>
            <div class="text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        </div>
    `;

    // Continue with the next card after a brief pause
    setTimeout(() => {
        loadingContainer.style.display = 'none';
        cardContainer.style.display = 'block';
        showCard(currentCardIndex);
    }, 1500);
}

/**
 * Display the session complete modal with stats
 */
function displaySessionCompleteModal() {
    // Clear the interval for checking new cards
    if (checkForNewDueCardsInterval) {
        clearInterval(checkForNewDueCardsInterval);
        checkForNewDueCardsInterval = null;
    }

    // Update stats in modal
    const totalReviewed = document.getElementById('totalReviewed');
    const againCount = document.getElementById('againCount');
    const hardCount = document.getElementById('hardCount');
    const goodCount = document.getElementById('goodCount');
    const easyCount = document.getElementById('easyCount');

    if (totalReviewed) totalReviewed.textContent = cards.length;
    if (againCount) againCount.textContent = sessionStats.again;
    if (hardCount) hardCount.textContent = sessionStats.hard;
    if (goodCount) goodCount.textContent = sessionStats.good;
    if (easyCount) easyCount.textContent = sessionStats.easy;

    // Calculate success rate and adjust feedback message
    const totalCards = cards.length;
    const successfulResponses = sessionStats.good + sessionStats.easy;
    const successRate = totalCards > 0 ? (successfulResponses / totalCards) * 100 : 0;

    // Update feedback message and icon based on performance
    const feedbackTitle = document.getElementById('sessionCompleteTitle');
    const feedbackMessage = document.getElementById('sessionCompleteMessage');
    const feedbackIcon = document.getElementById('sessionCompleteIcon');

    if (feedbackTitle && feedbackMessage && feedbackIcon) {
        if (sessionStats.again > totalCards * 0.5) {
            // Mostly "again" responses - user struggled significantly
            feedbackTitle.textContent = 'Session Completed';
            feedbackMessage.textContent = 'Keep practicing! These words need more review.';
            feedbackIcon.className = 'fas fa-book text-primary';
        } else if (successRate < 40) {
            // Low success rate - user had difficulty
            feedbackTitle.textContent = 'Session Completed';
            feedbackMessage.textContent = "Don't worry, spaced repetition will help you master these words.";
            feedbackIcon.className = 'fas fa-sync text-info';
        } else if (successRate < 70) {
            // Moderate success rate
            feedbackTitle.textContent = 'Good Progress!';
            feedbackMessage.textContent = "You're making progress with these words.";
            feedbackIcon.className = 'fas fa-thumbs-up text-info';
        } else {
            // High success rate
            feedbackTitle.textContent = 'Well done!';
            feedbackMessage.textContent = "Great job! You're mastering these words.";
            feedbackIcon.className = 'fas fa-check-circle text-success';
        }
    }

    // Get current streak from server
    fetch('/srs/api/statistics')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.statistics) {
                const currentStreak = document.getElementById('currentStreak');
                if (currentStreak) {
                    currentStreak.textContent = data.statistics.streak;
                }
            }
        })
        .catch(error => {
            console.error('Error getting statistics:', error);
        });

    // Show modal
    const sessionCompleteModal = document.getElementById('sessionCompleteModal');
    if (sessionCompleteModal) {
        try {
            const modal = new bootstrap.Modal(sessionCompleteModal);
            modal.show();
        } catch (error) {
            console.error('Error showing modal:', error);
            // Fallback to simple display change if Bootstrap is not available
            sessionCompleteModal.style.display = 'block';
        }
    }
}