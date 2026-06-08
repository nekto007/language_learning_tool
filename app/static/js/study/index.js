// Quiz modal
let selectedDeckId = null;

function openQuizModal(deckId, wordCount, deckTitle) {
    selectedDeckId = deckId;
    document.getElementById('modal-deck-title').textContent = deckTitle;
    document.getElementById('modal-deck-count').textContent = wordCount;

    // Set default limit
    const quizLimit = document.getElementById('quiz-limit');
    quizLimit.max = wordCount;
    quizLimit.value = Math.min(20, wordCount);

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('quizLimitModal'));
    modal.show();
}

function startQuiz() {
    const allWords = document.getElementById('quiz-all-words').checked;
    const limit = document.getElementById('quiz-limit').value;

    const startBtn = document.querySelector('.decks-modal__btn--start');
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:spin .6s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Загрузка...';
    }

    let url = `/study/quiz/deck/${selectedDeckId}`;
    if (!allWords && limit) {
        url += `?limit=${limit}`;
    }

    window.location.href = url;
}

// Toggle limit input based on checkbox
document.addEventListener('DOMContentLoaded', function() {
    const allWordsCheckbox = document.getElementById('quiz-all-words');
    const limitInput = document.getElementById('quiz-limit');

    if (allWordsCheckbox && limitInput) {
        allWordsCheckbox.addEventListener('change', function() {
            limitInput.disabled = this.checked;
        });
    }
});

function confirmDelete(deckId, deckTitle) {
    if (confirm(`Вы уверены, что хотите удалить колоду "${deckTitle}"?`)) {
        // Create form and submit
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/study/my-decks/${deckId}/delete`;

        // Add CSRF token
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        if (csrfToken) {
            const csrfInput = document.createElement('input');
            csrfInput.type = 'hidden';
            csrfInput.name = 'csrf_token';
            csrfInput.value = csrfToken.content;
            form.appendChild(csrfInput);
        }

        document.body.appendChild(form);
        form.submit();
    }
}

// Event listeners for deck buttons (XSS-safe via data attributes)
document.addEventListener('DOMContentLoaded', function() {
    // Quiz modal buttons
    document.querySelectorAll('.btn-quiz-modal').forEach(btn => {
        btn.addEventListener('click', function() {
            const deckId = parseInt(this.dataset.deckId);
            const wordCount = parseInt(this.dataset.wordCount);
            const deckTitle = this.dataset.deckTitle;
            openQuizModal(deckId, wordCount, deckTitle);
        });
    });

    // Copy deck form loading state
    document.querySelectorAll('.decks-card__copy-form').forEach(form => {
        form.addEventListener('submit', function() {
            const btn = this.querySelector('button[type="submit"]');
            if (btn) {
                btn.disabled = true;
                const label = btn.querySelector('.decks-card__btn-label');
                if (label) label.textContent = 'Копирую...';
            }
        });
    });

    // Delete deck buttons
    document.querySelectorAll('.btn-delete-deck').forEach(btn => {
        btn.addEventListener('click', function() {
            const deckId = parseInt(this.dataset.deckId);
            const deckTitle = this.dataset.deckTitle;
            confirmDelete(deckId, deckTitle);
        });
    });
});

// Deck search functionality
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('deck-search');
    const clearButton = document.getElementById('clear-search');
    const decksList = document.getElementById('decks-list');
    const deckCountBadge = document.getElementById('deck-count');

    if (searchInput && decksList && clearButton && deckCountBadge) {
        const cards = Array.from(decksList.querySelectorAll('.decks-card'));
        const totalDecks = cards.length;

        searchInput.addEventListener('input', function() {
            const query = this.value.toLowerCase().trim();

            // Show/hide clear button
            clearButton.classList.toggle('decks-search__clear--visible', !!query);

            let visibleCount = 0;

            cards.forEach(card => {
                // Get deck title and description
                const titleElement = card.querySelector('.decks-card__title');
                const descElement = card.querySelector('.decks-card__desc');

                const title = titleElement ? titleElement.textContent.toLowerCase() : '';
                const description = descElement ? descElement.textContent.toLowerCase() : '';

                // Check if query matches title or description
                if (title.includes(query) || description.includes(query)) {
                    card.style.display = '';
                    visibleCount++;
                } else {
                    card.style.display = 'none';
                }
            });

            // Update counter
            if (query) {
                deckCountBadge.textContent = `${visibleCount} из ${totalDecks}`;
            } else {
                deckCountBadge.textContent = totalDecks;
            }

            // Show "no results" message if needed
            if (visibleCount === 0 && query) {
                let noResultsDiv = document.getElementById('no-results-message');
                if (!noResultsDiv) {
                    noResultsDiv = document.createElement('div');
                    noResultsDiv.id = 'no-results-message';
                    noResultsDiv.className = 'decks-empty';
                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.setAttribute('width', '40'); svg.setAttribute('height', '40');
                    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('fill', 'none');
                    svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '2');
                    svg.innerHTML = '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>';
                    const p = document.createElement('p');
                    noResultsDiv.appendChild(svg);
                    noResultsDiv.appendChild(p);
                    decksList.appendChild(noResultsDiv);
                }
                const p = noResultsDiv.querySelector('p');
                p.textContent = `Колоды не найдены по запросу: "${query}"`;
            } else {
                const noResultsMsg = document.getElementById('no-results-message');
                if (noResultsMsg) {
                    noResultsMsg.remove();
                }
            }
        });

        // Clear search
        clearButton.addEventListener('click', function() {
            searchInput.value = '';
            searchInput.dispatchEvent(new Event('input'));
            searchInput.focus();
        });

        // Allow ESC key to clear search
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                this.value = '';
                this.dispatchEvent(new Event('input'));
                this.blur();
            }
        });
    }


});

// Vocabulary growth sparkline (task 39)
(function () {
    var canvas = document.getElementById('vocabGrowthChart');
    if (!canvas) return;
    var counts = window.STUDY_VOCAB_COUNTS || [];
    if (!counts.length) return;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    var w = canvas.width, h = canvas.height;
    var max = Math.max.apply(null, counts) || 1;
    var step = w / (counts.length - 1 || 1);
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    counts.forEach(function (v, i) {
        var x = i * step;
        var y = h - (v / max) * (h - 2) - 1;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--color-primary') || '#6366f1';
    ctx.lineWidth = 1.5;
    ctx.stroke();
}());
