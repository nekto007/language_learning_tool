/**
 * SRS (Spaced Repetition System) Integration
 * Handles integration with spaced repetition decks
 * Fully refactored to fix Import to Deck functionality
 */

// Используем область видимости для предотвращения конфликтов с глобальными переменными
(function() {
  // Локальные переменные вместо глобальных
  let _selectedWords = [];
  let _decksLoaded = false;

  // Инициализация при загрузке DOM
  document.addEventListener('DOMContentLoaded', function() {
    initSrsIntegration();
  });

  /**
   * Инициализация функциональности SRS
   */
  function initSrsIntegration() {
    // Выпадающий список импорта
    const importDropdown = document.getElementById('importToDeckDropdown');
    if (importDropdown) {
      // Используем событие Bootstrap для загрузки колод при открытии
      importDropdown.addEventListener('show.bs.dropdown', function() {
        console.log('Import dropdown opened - loading decks');
        loadDecks();
      });

      // Также добавляем обработчик клика как запасной вариант
      importDropdown.addEventListener('click', function() {
        if (!_decksLoaded) {
          console.log('Import dropdown clicked - loading decks');
          setTimeout(function() {
            loadDecks();
          }, 50);
        }
      });
    }

    // Кнопка создания новой колоды
    const createDeckBtn = document.getElementById('createNewDeckBtn');
    if (createDeckBtn) {
      createDeckBtn.addEventListener('click', function(e) {
        e.preventDefault();
        showCreateDeckModal();
      });
    }

    // Кнопка создания колоды со словами
    const createDeckWithWordsBtn = document.getElementById('createDeckWithWordsBtn');
    if (createDeckWithWordsBtn) {
      createDeckWithWordsBtn.addEventListener('click', function(e) {
        e.preventDefault();
        createDeckWithWords();
      });
    }

    // Кнопка импорта слов в колоду
    const importWordsToDeckBtn = document.getElementById('importWordsToDeckBtn');
    if (importWordsToDeckBtn) {
      importWordsToDeckBtn.addEventListener('click', function(e) {
        e.preventDefault();
        importWordsToDeck();
      });
    }

    // Добавляем обработчик событий для элементов колоды через делегирование
    document.addEventListener('click', function(e) {
      const deckItem = e.target.closest('.deck-item');
      if (deckItem) {
        e.preventDefault();
        const deckId = deckItem.dataset.deckId;
        const deckName = deckItem.textContent.trim();

        if (deckId) {
          console.log(`Deck item clicked: ${deckName} (${deckId})`);
          showImportToDeckModal(deckId, deckName);
        }
      }
    });

    // Настройка отслеживания выбора слов
    initWordSelection();

    // Исправление проблем с фильтром статуса
    fixAllWordsFilter();
  }

  /**
   * Инициализация отслеживания выбора слов
   */
  function initWordSelection() {
    // Используем существующий модуль выбора слов, если доступен
    if (window.wordSelection && typeof window.wordSelection.getSelectedWordIds === 'function') {

      // Инициализируем с текущим выбором
      _selectedWords = window.wordSelection.getSelectedWordIds();

      // Обновляем UI
      updateSelectionCounters();
    } else {
      console.log('Setting up custom word selection tracking');

      // Добавляем обработчик события изменения для чекбоксов
      document.addEventListener('change', function(e) {
        if (e.target.classList.contains('word-checkbox') || e.target.id === 'selectAll') {
          console.log('Selection changed - updating tracking');
          updateSelectedWords();
        }
      });

      // Начальное обновление
      updateSelectedWords();
    }
  }

  /**
   * Обновление отслеживания выбранных слов
   */
  function updateSelectedWords() {
    // Получаем ID выбранных слов из чекбоксов
    const checkboxes = document.querySelectorAll('input.word-checkbox:checked');
    _selectedWords = Array.from(checkboxes)
      .map(checkbox => parseInt(checkbox.value || checkbox.dataset.wordId || '0', 10))
      .filter(id => id > 0);

    console.log(`Selected words updated: ${_selectedWords.length} words`);

    // Обновляем счетчики UI
    updateSelectionCounters();
  }

  /**
   * Получение ID выбранных слов для операций
   * @returns {Array} Массив ID выбранных слов
   */
  function getSelectedWordIds() {
    // Используем модуль wordSelection, если доступен
    if (window.wordSelection && typeof window.wordSelection.getSelectedWordIds === 'function') {
      return window.wordSelection.getSelectedWordIds();
    }

    // Иначе используем наши отслеживаемые ID
    return _selectedWords;
  }

  /**
   * Обновление счетчиков выбора в UI
   */
  function updateSelectionCounters() {
    const count = _selectedWords.length;

    // Обновляем главный счетчик
    const selectedCount = document.getElementById('selectedCount');
    if (selectedCount) {
      selectedCount.textContent = `${count} selected`;
    }

    // Обновляем счетчики в модальных окнах
    const counters = document.querySelectorAll('#selectedWordsCount, #importWordsCount, #ankiSelectedWordsCount');
    counters.forEach(counter => {
      if (counter) {
        counter.textContent = count;
      }
    });

    // Обновляем состояние кнопок - ИЗМЕНЕНИЕ: не отключаем Import to Deck
    const bulkButtons = document.querySelectorAll('#bulkActionsBtn, #createAnkiBtn');
    bulkButtons.forEach(button => {
      if (button) {
        button.disabled = count === 0;
      }
    });

    // Кнопка Import to Deck всегда активна
    const importButton = document.getElementById('importToDeckDropdown');
    if (importButton) {
      importButton.disabled = false;
    }

    // Кнопки действий в модальных окнах
    const actionButtons = document.querySelectorAll('#createDeckWithWordsBtn, #importWordsToDeckBtn, #exportAnkiBtn');
    actionButtons.forEach(button => {
      if (button) {
        button.disabled = count === 0;
      }
    });
  }

  /**
   * Загрузка колод через API
   */
  async function loadDecks() {
    console.log('Loading decks for import dropdown');

    const container = document.getElementById('existingDecksContainer');
    if (!container) {
      console.error('Decks container not found');
      return;
    }

    // Показываем состояние загрузки
    container.innerHTML = `
      <div class="text-center py-2">
        <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
        <span class="ms-2">Loading decks...</span>
      </div>
    `;

    try {
      // Устанавливаем запрос с таймаутом
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);

      // Делаем запрос API
      const response = await fetch('/srs/api/decks', {
        signal: controller.signal,
        headers: {
          'Accept': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        }
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`Server returned status: ${response.status}`);
      }

      // Разбираем ответ
      const data = await response.json();

      if (!data.success || !Array.isArray(data.decks)) {
        throw new Error('Invalid API response format');
      }

      // Обрабатываем колоды
      const decks = data.decks;
      console.log(`Loaded ${decks.length} decks from API`);

      if (decks.length > 0) {
        // Обновляем выбор колоды в модальном окне
        const select = document.getElementById('targetDeckSelect');
        if (select) {
          select.innerHTML = '<option value="" disabled selected>Choose a deck</option>';

          decks.forEach(deck => {
            const option = document.createElement('option');
            option.value = deck.id;
            option.textContent = deck.name;
            select.appendChild(option);
          });
        }

        // Формируем HTML для выпадающего меню
        let html = '';
        decks.forEach(deck => {
          html += `
            <a href="#" class="list-group-item list-group-item-action deck-item py-2" 
               data-deck-id="${deck.id}" 
               data-deck-name="${deck.name}">
               ${deck.name}
            </a>
          `;
        });

        container.innerHTML = `<div class="list-group">${html}</div>`;
      } else {
        container.innerHTML = `
          <div class="text-center py-2">
            <p class="text-muted mb-2">No decks available</p>
            <button class="btn btn-sm btn-primary" id="createNewDeckFromEmpty">
              <i class="bi bi-plus-lg me-1"></i> Create New Deck
            </button>
          </div>
        `;

        // Добавляем обработчик события для кнопки создания колоды
        document.getElementById('createNewDeckFromEmpty')?.addEventListener('click', function(e) {
          e.preventDefault();
          showCreateDeckModal();
        });
      }

      // Отмечаем колоды как загруженные
      _decksLoaded = true;
    } catch (error) {
      console.error('Error loading decks:', error);

      // Показываем ошибку с кнопкой повтора
      container.innerHTML = `
        <div class="text-center py-2">
          <div class="alert alert-danger py-2 mb-2">
            Failed to load decks
          </div>
          <button class="btn btn-sm btn-outline-secondary" onclick="loadDecks()">
            <i class="bi bi-arrow-repeat me-1"></i> Try Again
          </button>
        </div>
      `;

      // Добавляем запасной вариант в селект
      const select = document.getElementById('targetDeckSelect');
      if (select) {
        select.innerHTML = '<option value="" disabled selected>Choose a deck</option>';
        select.innerHTML += '<option value="1">Main Deck</option>';
      }

      // Отмечаем колоды как не загруженные, чтобы попробовать снова в следующий раз
      _decksLoaded = false;
    }
  }

  /**
   * Показать модальное окно создания колоды
   */
  function showCreateDeckModal() {
    console.log('Showing Create Deck modal');

    const selectedIds = getSelectedWordIds();

    if (selectedIds.length === 0) {
      showToast('Please select at least one word', 'warning');
      return;
    }

    // Обновляем число выбранных слов
    const countElem = document.getElementById('selectedWordsCount');
    if (countElem) {
      countElem.textContent = selectedIds.length;
    }

    // Сбрасываем форму
    const form = document.getElementById('createDeckForm');
    if (form) {
      form.reset();
    }

    // Показываем модальное окно
    const modal = new bootstrap.Modal(document.getElementById('createDeckModal'));
    modal.show();
  }

  /**
   * Показать модальное окно импорта в колоду
   */
  function showImportToDeckModal(deckId, deckName) {
    console.log(`Showing Import to Deck modal for deck: ${deckName}`);

    const selectedIds = getSelectedWordIds();

    if (selectedIds.length === 0) {
      // Показываем предупреждение, но продолжаем
      showToast('No words selected. To import words, please select them first.', 'warning');

      // При желании можно прекратить здесь, если хотите, чтобы модальное окно
      // не открывалось совсем без выбранных слов
      // return;
    }

    // Устанавливаем выбранную колоду в выпадающем списке
    const select = document.getElementById('targetDeckSelect');
    if (select) {
      // Проверяем, существует ли уже опция
      let option = Array.from(select.options).find(opt => opt.value === deckId);

      if (!option) {
        // Создаем опцию, если она не существует
        option = document.createElement('option');
        option.value = deckId;
        option.textContent = deckName;
        select.appendChild(option);
      }

      // Выбираем опцию
      select.value = deckId;
    }

    // Обновляем заголовок модального окна
    const modalTitle = document.getElementById('importToDeckModalLabel');
    if (modalTitle) {
      modalTitle.textContent = 'Import to Deck: ' + deckName;
    }

    // Обновляем количество выбранных слов
    const countElem = document.getElementById('importWordsCount');
    if (countElem) {
      countElem.textContent = selectedIds.length;
    }

    // Показываем модальное окно
    const modal = new bootstrap.Modal(document.getElementById('importToDeckModal'));
    modal.show();
  }

  /**
   * Создать новую колоду с выбранными словами
   */
  async function createDeckWithWords() {
    console.log('Creating new deck with selected words');

    // Получаем ID выбранных слов
    const selectedIds = getSelectedWordIds();

    if (selectedIds.length === 0) {
      showToast('Please select at least one word', 'warning');
      return;
    }

    // Получаем имя колоды и описание
    const deckName = document.getElementById('deckNameInput').value.trim();
    const description = document.getElementById('deckDescriptionInput')?.value.trim() || '';

    if (!deckName) {
      showToast('Please enter a deck name', 'warning');
      return;
    }

    // Обновляем состояние кнопки
    const button = document.getElementById('createDeckWithWordsBtn');
    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Creating...';

    try {
      // Отправляем запрос API
      const response = await fetch('/srs/api/deck/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          name: deckName,
          description: description,
          word_ids: selectedIds
        })
      });

      if (!response.ok) {
        throw new Error(`Server returned status: ${response.status}`);
      }

      const data = await response.json();

      if (data.success) {
        // Закрываем модальное окно
        const modal = bootstrap.Modal.getInstance(document.getElementById('createDeckModal'));
        if (modal) {
          modal.hide();
        }

        // Показываем сообщение об успехе
        showToast(`Deck "${deckName}" created successfully with ${selectedIds.length} words`, 'success');

        // Сбрасываем выбор
        clearSelection();

        // Ждем немного, затем перезагружаем страницу для отображения изменений
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      } else {
        showToast(data.error || 'Failed to create deck', 'danger');
      }
    } catch (error) {
      console.error('Error creating deck:', error);
      showToast('Network error when creating deck', 'danger');
    } finally {
      // Восстанавливаем кнопку
      button.disabled = false;
      button.innerHTML = originalText;
    }
  }

  /**
   * Импортировать выбранные слова в колоду
   */
  async function importWordsToDeck() {
  console.log('Importing selected words to deck');

  // Get selected word IDs
  const selectedIds = getSelectedWordIds();

  if (selectedIds.length === 0) {
    showToast('Please select at least one word', 'warning');
    return;
  }

  // Get selected deck
  const select = document.getElementById('targetDeckSelect');
  if (!select || !select.value) {
    showToast('Please select a deck', 'warning');
    return;
  }

  const deckId = select.value;
  const deckName = select.options[select.selectedIndex].text;

  // Update button state
  const button = document.getElementById('importWordsToDeckBtn');
  const originalText = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Importing...';

  try {
    // Send API request to the CORRECT endpoint with the CORRECT parameter names
    const response = await fetch('/srs/api/import/words', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({
        deckId: deckId,
        wordIds: selectedIds
      })
    });

    if (!response.ok) {
      throw new Error(`Server returned status: ${response.status}`);
    }

    const data = await response.json();

    if (data.success) {
      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('importToDeckModal'));
      if (modal) {
        modal.hide();
      }

      // Show success message
      showToast(`Successfully imported ${selectedIds.length} words to "${deckName}"`, 'success');

      // Clear selection
      clearSelection();

      // Wait a bit, then reload page to show changes
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } else {
      showToast(data.error || 'Failed to import words', 'danger');
    }
  } catch (error) {
    console.error('Error importing words:', error);
    showToast('Network error when importing words', 'danger');
  } finally {
    // Restore button
    button.disabled = false;
    button.innerHTML = originalText;
  }
}

/**
 * Corrected createDeckWithWords function for SRS integration
 * Fixes the API endpoint and parameter naming issues
 */
async function createDeckWithWords() {
  console.log('Creating new deck with selected words');

  // Get selected word IDs
  const selectedIds = getSelectedWordIds();

  if (selectedIds.length === 0) {
    showToast('Please select at least one word', 'warning');
    return;
  }

  // Get deck name and description
  const deckName = document.getElementById('deckNameInput').value.trim();
  const description = document.getElementById('deckDescriptionInput')?.value.trim() || '';

  if (!deckName) {
    showToast('Please enter a deck name', 'warning');
    return;
  }

  // Update button state
  const button = document.getElementById('createDeckWithWordsBtn');
  const originalText = button.innerHTML;
  button.disabled = true;
  button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Creating...';

  try {
    // Send API request to the CORRECT endpoint with the CORRECT parameter names
    const response = await fetch('/srs/api/import/deck', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({
        deckName: deckName,
        description: description,
        wordIds: selectedIds
      })
    });

    if (!response.ok) {
      throw new Error(`Server returned status: ${response.status}`);
    }

    const data = await response.json();

    if (data.success) {
      // Close modal
      const modal = bootstrap.Modal.getInstance(document.getElementById('createDeckModal'));
      if (modal) {
        modal.hide();
      }

      // Show success message
      showToast(`Deck "${deckName}" created successfully with ${selectedIds.length} words`, 'success');

      // Clear selection
      clearSelection();

      // Wait a bit, then reload page to show changes
      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } else {
      showToast(data.error || 'Failed to create deck', 'danger');
    }
  } catch (error) {
    console.error('Error creating deck:', error);
    showToast('Network error when creating deck', 'danger');
  } finally {
    // Restore button
    button.disabled = false;
    button.innerHTML = originalText;
  }
}

  /**
   * Очистить выбор слов
   */
  function clearSelection() {
    console.log('Clearing word selection');

    // Снимаем выбор со всех чекбоксов
    document.querySelectorAll('.word-checkbox, #selectAll').forEach(checkbox => {
      checkbox.checked = false;
    });

    // Очищаем массив выбора
    _selectedWords = [];

    // Обновляем UI
    updateSelectionCounters();

    // Обновляем модуль wordSelection, если доступен
    if (window.wordSelection) {
      if (Array.isArray(window.wordSelection.selectedWordIds)) {
        window.wordSelection.selectedWordIds = [];
      }

      if (typeof window.wordSelection.updateAllSelectionCounters === 'function') {
        window.wordSelection.updateAllSelectionCounters();
      }

      if (typeof window.wordSelection.updateSelectAllCheckbox === 'function') {
        window.wordSelection.updateSelectAllCheckbox();
      }

      if (typeof window.wordSelection.updateBulkActionState === 'function') {
        window.wordSelection.updateBulkActionState();
      }
    }
  }

  /**
   * Обновить статус слова через API
   * @param {number} wordId - ID слова
   * @param {number} status - Новый код статуса
   * @returns {Promise} - Promise с ответом API
   */
  async function updateWordStatus(wordId, status) {
    try {
      const response = await fetch('/api/update_word_status', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          word_id: wordId,
          status: status
        })
      });

      return await response.json();
    } catch (error) {
      console.error('Error updating word status:', error);
      return { success: false, message: 'Network error when updating status' };
    }
  }

  /**
   * Исправление для фильтра "All Words", чтобы все слова отображались
   */
  function fixAllWordsFilter() {

    // Проверяем, находимся ли мы в представлении "All words"
    const isAllWordsView = document.querySelector('.status-tab.active:not([class*="status-tab-"])') !== null;

    if (isAllWordsView) {
      // Делаем все строки слов видимыми
      document.querySelectorAll('.word-row').forEach(row => {
        // Удаляем любой inline-стиль, который может скрывать строку
        row.style.display = '';

        // Удаляем любые классы, которые могут скрывать строку
        if (row.classList.contains('d-none')) {
          row.classList.remove('d-none');
        }

        // Принудительно показываем, если все еще скрыто
        const isHidden = window.getComputedStyle(row).display === 'none';
        if (isHidden) {
          row.style.display = 'table-row';
        }
      });

      // Добавляем стиль переопределения для противодействия любым правилам CSS
      const style = document.createElement('style');
      style.textContent = `
        /* Override for All Words filter */
        .status-tab.active:not([class*="status-tab-"]) ~ .card-body .word-row {
          display: table-row !important;
          visibility: visible !important;
        }
      `;
      document.head.appendChild(style);

      // Настраиваем наблюдатель для поддержания видимости после изменений DOM
      const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
          if (mutation.type === 'childList' ||
              (mutation.type === 'attributes' &&
              (mutation.attributeName === 'style' || mutation.attributeName === 'class'))) {
            // Повторно применяем исправление к любым измененным элементам
            document.querySelectorAll('.word-row').forEach(row => {
              if (window.getComputedStyle(row).display === 'none') {
                row.style.display = 'table-row';
              }
            });
          }
        });
      });

      const wordRows = document.querySelector('.words-table tbody');
      if (wordRows) {
        observer.observe(wordRows, {
          childList: true,
          subtree: true,
          attributes: true,
          attributeFilter: ['style', 'class']
        });
      }
    }
  }

  /**
   * Показать уведомление toast
   * @param {string} message - Сообщение для отображения
   * @param {string} type - Тип Bootstrap (success, danger, warning, info)
   */
  function showToast(message, type = 'info') {
    // Создаем контейнер для toast, если он не существует
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      document.body.appendChild(container);
    }

    // Создаем элемент toast
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.setAttribute('id', toastId);

    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          ${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" 
                data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;

    // Добавляем в контейнер
    container.appendChild(toast);

    // Инициализируем и показываем toast с помощью Bootstrap
    try {
      const bsToast = new bootstrap.Toast(toast, {
        delay: 3000,
        autohide: true
      });

      bsToast.show();

      // Удаляем toast после скрытия
      toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
      });
    } catch (error) {
      // Запасной вариант, если Toast Bootstrap недоступен
      console.error('Bootstrap Toast not available:', error);

      // Простая CSS-анимация как запасной вариант
      toast.style.opacity = '1';
      toast.style.transition = 'opacity 0.5s';

      setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
          toast.remove();
        }, 500);
      }, 3000);
    }
  }

  // Делаем функции доступными глобально, но с другими именами
  window.srsTools = {
    loadDecks: loadDecks,
    showCreateDeckModal: showCreateDeckModal,
    createDeckWithWords: createDeckWithWords,
    importWordsToDeck: importWordsToDeck,
    clearSelection: clearSelection,
    showToast: showToast
  };
})();