/**
 * Quiz Deck Editor
 * Handles word addition with autocomplete and inline editing
 */

class QuizDeckEditor {
    constructor(deckId, csrfToken) {
        this.deckId = deckId;
        this.csrfToken = csrfToken;
        this.currentWordInput = null;
        this.autocompleteTimeout = null;
        this.selectedWordId = null;

        this.initializeEventListeners();
    }

    initializeEventListeners() {
        // Add word form
        const addWordForm = document.getElementById('add-word-form');
        if (addWordForm) {
            addWordForm.addEventListener('submit', (e) => this.handleAddWord(e));
        }

        // English input autocomplete
        const englishInput = document.getElementById('new-word-english');
        if (englishInput) {
            englishInput.addEventListener('input', (e) => this.handleEnglishInput(e));
            englishInput.addEventListener('keydown', (e) => this.handleKeyDown(e));
            englishInput.addEventListener('blur', () => {
                // Delay hiding to allow click on autocomplete item
                setTimeout(() => this.hideAutocomplete(), 200);
            });
        }

        // Close autocomplete when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.autocomplete-wrapper')) {
                this.hideAutocomplete();
            }
        });
    }

    handleEnglishInput(e) {
        const query = e.target.value.trim();

        // Clear previous timeout
        clearTimeout(this.autocompleteTimeout);

        if (query.length < 2) {
            this.hideAutocomplete();
            this.clearRussianInput();
            this.selectedWordId = null;
            return;
        }

        // Debounce autocomplete search
        this.autocompleteTimeout = setTimeout(() => {
            this.searchWord(query);
        }, 300);
    }

    async searchWord(query) {
        try {
            const response = await fetch(`/admin/api/words/search?q=${encodeURIComponent(query)}&limit=10`);
            if (!response.ok) throw new Error('Search failed');

            const words = await response.json();
            this.showAutocomplete(words);
        } catch (error) {
            console.error('Error searching words:', error);
        }
    }

    showAutocomplete(words) {
        const dropdown = document.getElementById('autocomplete-dropdown');
        if (!dropdown) return;

        if (words.length === 0) {
            this.hideAutocomplete();
            this.clearRussianInput();
            this.selectedWordId = null;
            return;
        }

        dropdown.innerHTML = words.map(word => `
            <div class="autocomplete-item"
                 data-word-id="${word.id}"
                 data-english="${this.escapeHtml(word.english)}"
                 data-russian="${this.escapeHtml(word.russian)}">
                <strong>${this.escapeHtml(word.english)}</strong> — ${this.escapeHtml(word.russian)}
            </div>
        `).join('');

        dropdown.classList.add('show');

        // Add click handlers to autocomplete items
        dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', () => this.selectWord(item));
        });
    }

    hideAutocomplete() {
        const dropdown = document.getElementById('autocomplete-dropdown');
        if (dropdown) {
            dropdown.classList.remove('show');
        }
    }

    selectWord(item) {
        const wordId = item.dataset.wordId;
        const english = item.dataset.english;
        const russian = item.dataset.russian;

        // Fill inputs
        document.getElementById('new-word-english').value = english;
        document.getElementById('new-word-russian').value = russian;

        // Store word ID
        this.selectedWordId = wordId;

        this.hideAutocomplete();
    }

    clearRussianInput() {
        const russianInput = document.getElementById('new-word-russian');
        if (russianInput && this.selectedWordId) {
            russianInput.value = '';
        }
    }

    handleKeyDown(e) {
        const dropdown = document.getElementById('autocomplete-dropdown');
        if (!dropdown || !dropdown.classList.contains('show')) return;

        const items = dropdown.querySelectorAll('.autocomplete-item');
        const activeItem = dropdown.querySelector('.autocomplete-item.active');
        let currentIndex = Array.from(items).indexOf(activeItem);

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                currentIndex = Math.min(currentIndex + 1, items.length - 1);
                this.setActiveItem(items, currentIndex);
                break;
            case 'ArrowUp':
                e.preventDefault();
                currentIndex = Math.max(currentIndex - 1, 0);
                this.setActiveItem(items, currentIndex);
                break;
            case 'Enter':
                e.preventDefault();
                if (activeItem) {
                    this.selectWord(activeItem);
                }
                break;
            case 'Escape':
                this.hideAutocomplete();
                break;
        }
    }

    setActiveItem(items, index) {
        items.forEach((item, i) => {
            item.classList.toggle('active', i === index);
        });
    }

    async handleAddWord(e) {
        e.preventDefault();
        e.stopPropagation();

        const englishInput = document.getElementById('new-word-english');
        const russianInput = document.getElementById('new-word-russian');

        const english = englishInput.value.trim();
        const russian = russianInput.value.trim();

        if (!english || !russian) {
            showToast('Заполните оба поля', 'warning');
            return false;
        }

        const formData = new FormData();
        formData.append('csrf_token', this.csrfToken);

        // Get word_id from hidden input
        const wordIdInput = document.getElementById('word-id-input');
        if (wordIdInput && wordIdInput.value) {
            formData.append('word_id', wordIdInput.value);
        }

        formData.append('custom_english', english);
        formData.append('custom_russian', russian);

        try {
            const response = await fetch(`/admin/quiz-decks/${this.deckId}/words/add`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json'
                },
                body: formData
            });

            if (response.ok) {
                const data = await response.json();

                // Clear form
                englishInput.value = '';
                russianInput.value = '';
                wordIdInput.value = '';
                this.selectedWordId = null;

                // Add new word to table
                addWordToTable(data.word);

                // Update word count
                updateWordCount();

                // Focus back to english input for quick adding
                englishInput.focus();

                showToast('Слово добавлено', 'success');
            } else {
                const data = await response.json().catch(() => ({}));
                showToast(data.message || 'Ошибка при добавлении слова', 'danger');
            }
        } catch (error) {
            console.error('Error adding word:', error);
            showToast('Ошибка при добавлении слова', 'danger');
        }

        return false;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Inline editing functions - make them global so they work with onclick
window.enableEdit = function(button) {
    const wordId = button.dataset.wordId;
    const engWord = button.dataset.english;
    const rusWord = button.dataset.russian;

    const engDisplay = document.getElementById(`eng-display-${wordId}`);
    const rusDisplay = document.getElementById(`rus-display-${wordId}`);

    engDisplay.innerHTML = `<input type="text" class="form-control form-control-sm" id="eng-input-${wordId}" value="${escapeHtml(engWord)}">`;
    rusDisplay.innerHTML = `<input type="text" class="form-control form-control-sm" id="rus-input-${wordId}" value="${escapeHtml(rusWord)}">`;

    // Hide view mode, show edit mode
    const viewMode = document.getElementById(`view-mode-${wordId}`);
    const editMode = document.getElementById(`edit-mode-${wordId}`);

    viewMode.classList.add('d-none');
    editMode.classList.remove('d-none');
};

window.cancelEdit = function(wordId) {
    // Restore original display without reload
    const viewMode = document.getElementById(`view-mode-${wordId}`);
    const editMode = document.getElementById(`edit-mode-${wordId}`);

    viewMode.classList.remove('d-none');
    editMode.classList.add('d-none');

    // Reload the page to restore original values
    window.location.reload();
};

window.saveEdit = async function(button) {
    const wordId = button.dataset.wordId;

    const engInput = document.getElementById(`eng-input-${wordId}`);
    const rusInput = document.getElementById(`rus-input-${wordId}`);

    if (!engInput || !rusInput) {
        alert('Ошибка: поля не найдены');
        return;
    }

    const engValue = engInput.value.trim();
    const rusValue = rusInput.value.trim();

    if (!engValue || !rusValue) {
        alert('Оба поля должны быть заполнены');
        return;
    }

    const form = document.getElementById(`edit-form-${wordId}`);
    const formData = new FormData();

    // Get CSRF token from form
    const csrfToken = form.querySelector('input[name="csrf_token"]').value;
    formData.append('csrf_token', csrfToken);
    formData.append('custom_english', engValue);
    formData.append('custom_russian', rusValue);

    try {
        const response = await fetch(form.action, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            },
            body: formData
        });

        if (response.ok) {
            const data = await response.json();

            // Update display without reload
            const engDisplay = document.getElementById(`eng-display-${wordId}`);
            const rusDisplay = document.getElementById(`rus-display-${wordId}`);

            // Add custom icon if word has custom translation
            const customIcon = data.word.has_custom
                ? ' <i class="fas fa-pen text-primary ms-1" title="Переопределен для этой колоды"></i>'
                : '';

            engDisplay.innerHTML = escapeHtml(data.word.english) + customIcon;
            rusDisplay.innerHTML = escapeHtml(data.word.russian) + customIcon;

            // Update data attributes in the edit button
            const viewMode = document.getElementById(`view-mode-${wordId}`);
            const editButton = viewMode.querySelector('button[data-word-id]');
            if (editButton) {
                editButton.dataset.english = data.word.english;
                editButton.dataset.russian = data.word.russian;
            }

            // Switch back to view mode
            const editMode = document.getElementById(`edit-mode-${wordId}`);
            viewMode.classList.remove('d-none');
            editMode.classList.add('d-none');

            // Show success message
            showToast(data.message, 'success');
        } else {
            const data = await response.json();
            showToast(data.message || 'Ошибка при сохранении', 'danger');
        }
    } catch (error) {
        console.error('Error saving word:', error);
        showToast('Ошибка при сохранении', 'danger');
    }
};

// Simple toast notification - make global
window.showToast = function(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 250px;';
    toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
};

window.escapeHtml = function(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
};

window.copyShareLink = function(link) {
    navigator.clipboard.writeText(link).then(() => {
        showToast('Ссылка скопирована!', 'success');
    }).catch(() => {
        showToast('Не удалось скопировать ссылку', 'danger');
    });
};

window.deleteWord = async function(button) {
    const wordId = button.dataset.wordId;
    const deckId = button.dataset.deckId;

    if (!confirm('Удалить это слово из колоды?')) {
        return;
    }

    try {
        const formData = new FormData();
        // Get CSRF token from page
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content
            || document.querySelector('input[name="csrf_token"]')?.value;

        if (csrfToken) {
            formData.append('csrf_token', csrfToken);
        }

        const response = await fetch(`/admin/quiz-decks/${deckId}/words/${wordId}/delete`, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            },
            body: formData
        });

        if (response.ok) {
            // Remove the row from table with animation
            const row = document.getElementById(`word-row-${wordId}`);
            if (row) {
                row.style.transition = 'opacity 0.3s';
                row.style.opacity = '0';
                setTimeout(() => {
                    row.remove();

                    // Update word count
                    updateWordCount();

                    showToast('Слово удалено из колоды', 'success');
                }, 300);
            }
        } else {
            const data = await response.json().catch(() => ({}));
            showToast(data.message || 'Ошибка при удалении', 'danger');
        }
    } catch (error) {
        console.error('Error deleting word:', error);
        showToast('Ошибка при удалении слова', 'danger');
    }
};

function addWordToTable(word) {
    const wordsList = document.getElementById('deck-words-list');
    if (!wordsList) {
        // If no table exists (no words), need to reload to show table structure
        window.location.reload();
        return;
    }

    // Get CSRF token
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

    // Create new row
    const newRow = document.createElement('tr');
    newRow.setAttribute('data-word-id', word.id);
    newRow.setAttribute('id', `word-row-${word.id}`);

    const customIcon = word.has_custom
        ? '<i class="fas fa-pen text-primary ms-1" title="Переопределен для этой колоды"></i>'
        : '';

    newRow.innerHTML = `
        <td>${wordsList.querySelectorAll('tr').length + 1}</td>
        <td class="word-display" id="eng-display-${word.id}">
            ${escapeHtml(word.english)}${customIcon}
        </td>
        <td class="word-display" id="rus-display-${word.id}">
            ${escapeHtml(word.russian)}${customIcon}
        </td>
        <td>
            <form method="post"
                  action="/admin/quiz-decks/${word.deck_id}/words/${word.id}/update"
                  class="edit-form d-none"
                  id="edit-form-${word.id}">
                <input type="hidden" name="csrf_token" value="${csrfToken}"/>
            </form>

            <div class="view-mode" id="view-mode-${word.id}">
                <button type="button"
                        class="btn btn-sm btn-outline-primary"
                        data-word-id="${word.id}"
                        data-english="${escapeHtml(word.english)}"
                        data-russian="${escapeHtml(word.russian)}"
                        onclick="enableEdit(this)"
                        title="Редактировать перевод для этой колоды">
                    <i class="fas fa-edit"></i>
                </button>
                <button type="button"
                        class="btn btn-sm btn-outline-danger"
                        data-word-id="${word.id}"
                        data-deck-id="${word.deck_id}"
                        onclick="deleteWord(this)"
                        title="Удалить из колоды">
                    <i class="fas fa-trash"></i>
                </button>
            </div>

            <div class="edit-mode d-none" id="edit-mode-${word.id}">
                <button type="button"
                        class="btn btn-sm btn-success"
                        data-word-id="${word.id}"
                        onclick="saveEdit(this)">
                    <i class="fas fa-save"></i>
                </button>
                <button type="button"
                        class="btn btn-sm btn-secondary"
                        onclick="cancelEdit(${word.id})">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        </td>
    `;

    // Add row to table
    wordsList.appendChild(newRow);

    // Animate new row
    newRow.style.opacity = '0';
    newRow.style.transition = 'opacity 0.3s';
    setTimeout(() => {
        newRow.style.opacity = '1';
    }, 10);
}

function updateWordCount() {
    const wordsList = document.getElementById('deck-words-list');
    if (!wordsList) return;

    const count = wordsList.querySelectorAll('tr').length;
    const header = document.querySelector('.card-header h5');
    if (header) {
        header.innerHTML = `<i class="fas fa-list me-2"></i>Слова в колоде (${count})`;
    }

    // Show info message if no words left
    if (count === 0) {
        const cardBody = wordsList.closest('.card-body');
        if (cardBody) {
            cardBody.innerHTML = `
                <div class="alert alert-info text-center">
                    <i class="fas fa-info-circle me-2"></i>
                    В колоде пока нет слов. Добавьте первое слово выше.
                </div>
            `;
        }
    } else {
        // Renumber rows
        wordsList.querySelectorAll('tr').forEach((row, index) => {
            const firstTd = row.querySelector('td:first-child');
            if (firstTd) {
                firstTd.textContent = index + 1;
            }
        });
    }
}
