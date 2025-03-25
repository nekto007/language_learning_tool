/**
 * Language Support Module
 * Provides bilingual support based on browser settings only
 */
class LanguageManager {
  constructor() {
    // Default language is English
    this.currentLang = 'en';

    // Translation dictionaries
    this.translations = {
      en: {
        // Navigation
        'decks': 'Decks',
        'statistics': 'Statistics',

        // Headers
        'studyDecks': 'Study Decks',
        'import': 'Import',
        'createDeck': 'Create Deck',

        // Table headers
        'deck': 'Deck',
        'new': 'New',
        'studying': 'Studying',
        'due': 'Due',

        // Empty state
        'noDecksYet': 'No Decks Yet',
        'noDecksDescription': 'You haven\'t created any decks yet. Create your first deck to start learning.',
        'createFirstDeck': 'Create First Deck',

        // Stats
        'todaysProgress': 'Today\'s Progress',
        'cardsReviewed': 'Cards Reviewed',
        'minutes': 'Minutes',
        'cardsPerMin': 'Cards/Min',
        'learningStreak': 'Learning Streak',
        'currentStreak': 'Current Streak',
        'longestStreak': 'Longest Streak',
        'consistency': 'Consistency',
        'activityCalendar': 'Activity Calendar',
        'dailyAverage': 'Daily average',
        'daysLearned': 'Days learned',
        'cards': 'cards',
        'days': 'days',
        'day': 'day',

        // Calendar Legend
        'noActivity': 'No activity',
        'scheduled': 'Scheduled',
        'oneToNineCards': '1-9 cards',
        'tenToTwentyNineCards': '10-29 cards',
        'thirtyPlusCards': '30+ cards',

        // Import Modal
        'importDeck': 'Import Deck',
        'importType': 'Import Type',
        'fromFile': 'From File',
        'fromWordList': 'From Word List',
        'selectFile': 'Select File',
        'supportedFormats': 'Supported formats: CSV, TXT, APKG (Anki)',
        'deckName': 'Deck Name',
        'enterDeckName': 'Enter deck name',
        'wordsList': 'Words List (one per line)',
        'cancel': 'Cancel',
        'startImport': 'Import',

        // Progress Modal
        'importProgress': 'Import Progress',
        'importing': 'Importing deck, please wait...',

        // Results Modal
        'importResults': 'Import Results',
        'importCompleted': 'Import completed successfully!',
        'importFailed': 'Import failed!',
        'ok': 'OK',

        // Alert messages
        'pleaseSelectFile': 'Please select a file to import',
        'pleaseEnterDeckName': 'Please enter a deck name',
        'pleaseEnterWords': 'Please enter words to import',
        'unexpectedError': 'An unexpected error occurred',
        'clearConfirmation': 'Are you sure you want to clear all your activity history?',

        // Statistics page
        'reviewed30Days': 'Reviewed (30 Days)',
        'studyingWords': 'Studying Words',
        'studiedWords': 'Studied Words',
        'inProgress': 'in progress',
        'completed': 'completed',
        'dailyActivity': 'Daily Activity',
        'wordsByStatus': 'Words by Status',
        'recentActivity': 'Recent Activity',
        'lastSevenDays': 'Last 7 days',
        'lastFourteenDays': 'Last 14 days',
        'lastThirtyDays': 'Last 30 days',
        'date': 'Date',
        'duration': 'Duration',
        'noActivityYet': 'No Activity Yet',
        'noActivityDescription': 'You haven\'t reviewed any cards yet. Start learning to see your progress here.'
      },
      ru: {
        // Navigation
        'decks': 'Колоды',
        'statistics': 'Статистика',

        // Headers
        'studyDecks': 'Колоды для изучения',
        'import': 'Импорт',
        'createDeck': 'Создать колоду',

        // Table headers
        'deck': 'Колода',
        'new': 'Новые',
        'studying': 'Изучаемые',
        'due': 'Ожидающие',

        // Empty state
        'noDecksYet': 'Пока нет колод',
        'noDecksDescription': 'Вы еще не создали ни одной колоды. Создайте свою первую колоду, чтобы начать обучение.',
        'createFirstDeck': 'Создать первую колоду',

        // Stats
        'todaysProgress': 'Прогресс за сегодня',
        'cardsReviewed': 'Карточек изучено',
        'minutes': 'Минут',
        'cardsPerMin': 'Карт/мин',
        'learningStreak': 'Серия обучения',
        'currentStreak': 'Текущая серия',
        'longestStreak': 'Рекордная серия',
        'consistency': 'Постоянство',
        'activityCalendar': 'Календарь активности',
        'dailyAverage': 'Среднее в день',
        'daysLearned': 'Дней изучения',
        'cards': 'карточек',
        'days': 'дней',
        'day': 'день',


        // Calendar Legend
        'noActivity': 'Нет активности',
        'scheduled': 'Запланировано',
        'oneToNineCards': '1-9 карточек',
        'tenToTwentyNineCards': '10-29 карточек',
        'thirtyPlusCards': '30+ карточек',

        // Import Modal
        'importDeck': 'Импортировать колоду',
        'importType': 'Тип импорта',
        'fromFile': 'Из файла',
        'fromWordList': 'Из списка слов',
        'selectFile': 'Выберите файл',
        'supportedFormats': 'Поддерживаемые форматы: CSV, TXT, APKG (Anki)',
        'deckName': 'Название колоды',
        'enterDeckName': 'Введите название колоды',
        'wordsList': 'Список слов (по одному на строку)',
        'cancel': 'Отмена',
        'startImport': 'Импортировать',

        // Progress Modal
        'importProgress': 'Прогресс импорта',
        'importing': 'Импортирование колоды, пожалуйста, подождите...',

        // Results Modal
        'importResults': 'Результаты импорта',
        'importCompleted': 'Импорт успешно завершен!',
        'importFailed': 'Импорт не удался!',
        'ok': 'ОК',

        // Alert messages
        'pleaseSelectFile': 'Пожалуйста, выберите файл для импорта',
        'pleaseEnterDeckName': 'Пожалуйста, введите название колоды',
        'pleaseEnterWords': 'Пожалуйста, введите слова для импорта',
        'unexpectedError': 'Произошла непредвиденная ошибка',
        'clearConfirmation': 'Вы уверены, что хотите очистить всю историю активности?',

        // Statistics page
        'reviewed30Days': 'Изучено (30 дней)',
        'studyingWords': 'Изучаемые слова',
        'studiedWords': 'Изученные слова',
        'inProgress': 'в процессе',
        'completed': 'завершено',
        'dailyActivity': 'Ежедневная активность',
        'wordsByStatus': 'Слова по статусу',
        'recentActivity': 'Недавняя активность',
        'lastSevenDays': 'Последние 7 дней',
        'lastFourteenDays': 'Последние 14 дней',
        'lastThirtyDays': 'Последние 30 дней',
        'date': 'Дата',
        'duration': 'Длительность',
        'noActivityYet': 'Пока нет активности',
        'noActivityDescription': 'Вы еще не изучали карточки. Начните обучение, чтобы увидеть свой прогресс здесь.'
      }
    };

    this.init();
  }

  /**
   * Initialize language settings
   */
  init() {
    // Detect browser language
    const browserLang = navigator.language || navigator.userLanguage;

    // If Russian is detected, set as current language
    if (browserLang.startsWith('ru')) {
      this.currentLang = 'ru';
    }

    console.log(`Language detected from browser: ${browserLang}, using: ${this.currentLang}`);

    // Apply translations
    this.applyTranslations();
  }

  /**
   * Get translation for a key
   * @param {string} key - Translation key
   * @returns {string} Translated text
   */
  translate(key) {
    if (!this.translations[this.currentLang]) {
      return key;
    }
    return this.translations[this.currentLang][key] || key;
  }

  /**
   * Apply translations to all elements with data-i18n attribute
   */
  applyTranslations() {
    // Apply to page title
    const pageTitle = document.querySelector('.decks-header__title');
    if (pageTitle) {
      pageTitle.textContent = this.translate(pageTitle.dataset.i18n || 'studyDecks');
    }

    // Apply to elements with data-i18n attribute
    document.querySelectorAll('[data-i18n]').forEach(element => {
      const key = element.dataset.i18n;
      const translation = this.translate(key);

      // Handle special cases
      if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
        if (element.placeholder) {
          element.placeholder = translation;
        }
      } else if (element.tagName === 'OPTION') {
        element.textContent = translation;
      } else {
        element.textContent = translation;
      }
    });

    // Special handling for specific elements
    this.updateTableHeaders();
    this.updateEmptyState();
    this.updateModals();
    this.updateButtons();
    this.updateStatisticsElements();
  }

  /**
   * Update table headers with translations
   */
  updateTableHeaders() {
    const headers = {
      '.deck-name[role="columnheader"]': 'deck',
      '.deck-new[role="columnheader"]': 'new',
      '.deck-studying[role="columnheader"]': 'studying',
      '.deck-due[role="columnheader"]': 'due'
    };

    Object.entries(headers).forEach(([selector, key]) => {
      const element = document.querySelector(selector);
      if (element) {
        element.textContent = this.translate(key);
      }
    });
  }

  /**
   * Update empty state content
   */
  updateEmptyState() {
    const emptyTitle = document.querySelector('.empty-state__title');
    const emptyText = document.querySelector('.empty-state__text');
    const emptyButton = document.querySelector('.empty-state .btn-primary');

    if (emptyTitle) emptyTitle.textContent = this.translate(emptyTitle.dataset.i18n || 'noDecksYet');
    if (emptyText) emptyText.textContent = this.translate(emptyText.dataset.i18n || 'noDecksDescription');
    if (emptyButton) {
      const icon = emptyButton.innerHTML.split('</i>')[0] + '</i> ';
      emptyButton.innerHTML = icon + this.translate(emptyButton.querySelector('span')?.dataset.i18n || 'createFirstDeck');
    }
  }

  /**
   * Update buttons with translations
   */
  updateButtons() {
    // Import button
    const importBtn = document.querySelector('#importDeckBtn');
    if (importBtn) {
      const importIcon = importBtn.innerHTML.split('</i>')[0] + '</i> ';
      const spanElement = importBtn.querySelector('span');
      if (spanElement) {
        importBtn.innerHTML = importIcon + this.translate(spanElement.dataset.i18n || 'import');
      }
    }

    // Create deck button
    const createDeckBtn = document.querySelector('a.btn-primary[href*="create_deck"]');
    if (createDeckBtn) {
      const createIcon = createDeckBtn.innerHTML.split('</i>')[0] + '</i> ';
      const spanElement = createDeckBtn.querySelector('span');
      if (spanElement) {
        createDeckBtn.innerHTML = createIcon + this.translate(spanElement.dataset.i18n || 'createDeck');
      }
    }
  }

  /**
   * Update statistics page specific elements
   */
  updateStatisticsElements() {
    // Update select options in statistics page
    const activityPeriod = document.getElementById('activityPeriod');
    if (activityPeriod) {
      Array.from(activityPeriod.options).forEach(option => {
        if (option.dataset.i18n) {
          option.textContent = this.translate(option.dataset.i18n);
        }
      });
    }

    // Update chart labels if Chart.js is initialized
    if (window.Chart && window.Chart.instances) {
      Object.values(window.Chart.instances).forEach(chart => {
        // Update labels if needed
        if (chart.config && chart.config.data && chart.config.data.labels) {
          const labels = chart.config.data.labels;
          // Translate specific known labels
          if (labels.includes('New')) {
            chart.config.data.labels = labels.map(label =>
              label === 'New' ? this.translate('new') :
              label === 'Studying' ? this.translate('studying') :
              label === 'Mastered' ? this.translate('mastered') : label
            );
            chart.update();
          }
        }
      });
    }
  }

  /**
   * Update modal content
   */
  updateModals() {
    // Import modal
    const importDeckModalLabel = document.querySelector('#importDeckModalLabel');
    if (importDeckModalLabel) {
      importDeckModalLabel.textContent = this.translate('importDeck');
    }

    const importTypeLabel = document.querySelector('label[for="importType"]');
    if (importTypeLabel) {
      importTypeLabel.textContent = this.translate('importType');
    }

    // Update select options
    const importTypeSelect = document.querySelector('#importType');
    if (importTypeSelect) {
      Array.from(importTypeSelect.options).forEach(option => {
        if (option.value === 'file') option.textContent = this.translate('fromFile');
        if (option.value === 'words') option.textContent = this.translate('fromWordList');
      });
    }

    // More form labels
    const deckFileLabel = document.querySelector('label[for="deckFile"]');
    if (deckFileLabel) {
      deckFileLabel.textContent = this.translate('selectFile');
    }

    const deckNameInputLabel = document.querySelector('label[for="deckNameInput"]');
    if (deckNameInputLabel) {
      deckNameInputLabel.textContent = this.translate('deckName');
    }

    const wordsListLabel = document.querySelector('label[for="wordsList"]');
    if (wordsListLabel) {
      wordsListLabel.textContent = this.translate('wordsList');
    }

    const wordsImportDeckNameLabel = document.querySelector('label[for="wordsImportDeckName"]');
    if (wordsImportDeckNameLabel) {
      wordsImportDeckNameLabel.textContent = this.translate('deckName');
    }

    // Support text
    const supportedFormatsText = document.querySelector('.form-text');
    if (supportedFormatsText) {
      supportedFormatsText.textContent = this.translate('supportedFormats');
    }

    // Placeholders
    const deckNameInput = document.querySelector('#deckNameInput');
    if (deckNameInput) {
      deckNameInput.placeholder = this.translate('enterDeckName');
    }

    const wordsImportDeckName = document.querySelector('#wordsImportDeckName');
    if (wordsImportDeckName) {
      wordsImportDeckName.placeholder = this.translate('enterDeckName');
    }

    // Progress message
    const importProgressMessage = document.querySelector('#importProgressMessage');
    if (importProgressMessage) {
      importProgressMessage.textContent = this.translate('importing');
    }

    // Update buttons
    const modalCancelBtns = document.querySelectorAll('.modal-footer .btn-secondary');
    modalCancelBtns.forEach(btn => {
      btn.textContent = this.translate('cancel');
    });

    const importBtn = document.querySelector('#startImportBtn');
    if (importBtn) {
      importBtn.textContent = this.translate('startImport');
    }

    const okBtn = document.querySelector('#importResultsOkBtn');
    if (okBtn) {
      okBtn.textContent = this.translate('ok');
    }

    // Modal titles
    const importProgressModalLabel = document.querySelector('#importProgressModalLabel');
    if (importProgressModalLabel) {
      importProgressModalLabel.textContent = this.translate('importProgress');
    }

    const importResultsModalLabel = document.querySelector('#importResultsModalLabel');
    if (importResultsModalLabel) {
      importResultsModalLabel.textContent = this.translate('importResults');
    }
  }
}

// Export for use in main app
export { LanguageManager };