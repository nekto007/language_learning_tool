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
        'backToDecks': 'Back to Decks',

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
        'noActivityDescription': 'You haven\'t reviewed any cards yet. Start learning to see your progress here.',

        // Deck detail page
        'word': 'Word',
        'translation': 'Translation',
        'interval': 'Interval',
        'repetitions': 'Repetitions',
        'nextReview': 'Next Review',
        'actions': 'Actions',
        'addWords': 'Add Words',
        'cardsToStudy': 'Cards to Study',
        'wordsInDeck': 'Words in Deck',
        'learning': 'Learning',
        'review': 'Review',
        'startReview': 'Start Review',
        'noCardsAvailable': 'No cards available for review at this time.',
        'mastered': 'Mastered',
        'today': 'Today',
        'noWordsInDeck': 'There are no words in this deck yet',
        'addWordsToBegin': 'Add words to begin studying with this deck',

        // Deck actions
        'editDeck': 'Edit Deck',
        'deckSettings': 'Deck Settings',
        'deleteDeck': 'Delete Deck',
        'moveCard': 'Move Card',
        'resetProgress': 'Reset Progress',
        'removeFromDeck': 'Remove from Deck',

        // Add word modal
        'addWordsToDeck': 'Add Words to Deck',
        'selectWordStatus': 'Select word status to add:',
        'newWords': 'New Words',
        'queuedWords': 'Queued Words',
        'activeWords': 'Active Words',
        'learnedWords': 'Learned Words',
        'searchWordPlaceholder': 'Search by word or translation...',
        'loadingWords': 'Loading words...',
        'addSelected': 'Add Selected',

        // Edit deck modal
        'description': 'Description',
        'enterDeckDescription': 'Enter deck description',
        'saveChanges': 'Save Changes',

        // Delete deck modal
        'warning': 'Warning:',
        'actionCannotBeUndone': 'This action cannot be undone.',
        'areYouSureDelete': 'Are you sure you want to delete the deck',
        'allCardsRemoved': 'All cards in this deck will be removed.',
        'delete': 'Delete',

        // Move card modal
        'selectTargetDeck': 'Select the target deck to move this card to:',
        'loadingDecks': 'Loading decks...',

        // Deck settings modal
        'dailyLimits': 'Daily Limits',
        'newCardsPerDay': 'New cards per day',
        'preset': 'Preset',
        'thisDeck': 'This deck',
        'todayOnly': 'Today only',
        'maxReviewsPerDay': 'Maximum reviews per day',
        'reviewLimitNoAffectNew': 'Review limit doesn\'t affect new cards',
        'limitsStartFromTop': 'Limits start from top',
        'globalSetting': 'Global setting',

        // New cards tab
        'newCards': 'New Cards',
        'learningSteps': 'Learning steps',
        'graduatingInterval': 'Graduating interval',
        'easyInterval': 'Easy interval',
        'insertionOrder': 'Insertion order',
        'sequential': 'Sequential (oldest first)',
        'random': 'Random',

        // Forgotten tab
        'forgotten': 'Forgotten',
        'relearningSteps': 'Relearning steps',
        'minimumInterval': 'Minimum interval',
        'lapseThreshold': 'Lapse threshold',
        'lapseAction': 'Lapse action',
        'tagOnly': 'Tag only',
        'suspend': 'Suspend',

        // Order tab
        'orderDisplay': 'Order Display',
        'newCardGathering': 'New card gathering',
        'byDeck': 'By deck',
        'newCardOrder': 'New card order',
        'byCardType': 'By card type',
        'byTimeAdded': 'By time added',
        'newAndReviewOrder': 'New and review order',
        'interleaveWithReviews': 'Interleave with reviews',
        'newFirst': 'New first',
        'reviewFirst': 'Review first',
        'interDayLearningOrder': 'Inter-day learning order',
        'byDue': 'By due',
        'reviewOrder': 'Review order',
        'dueThenRandom': 'Due then random',
        'strictlyByDue': 'Strictly by due',
        'burying': 'Burying',
        'buryNewRelated': 'Bury new related until next day',
        'buryReviewsRelated': 'Bury reviews related until next day',
        'buryInterday': 'Bury interday learning related cards',

        // Timer tab
        'timer': 'Timer',
        'maxAnswerTime': 'Maximum seconds for answer',
        'showAnswerTimer': 'Show answer timer',
        'stopTimerOnAnswer': 'Stop timer on answer',
        'autoPreview': 'Auto Preview',
        'secondsShowQuestion': 'Seconds to show question for',
        'secondsShowAnswer': 'Seconds to show answer for',
        'waitForAudio': 'Wait for audio',
        'answerAction': 'Answer action',
        'buryCard': 'Bury card',
        'again': 'Again',
        'good': 'Good',
        'easy': 'Easy',

        // Audio tab
        'audio': 'Audio',
        'disableAutoPlay': 'Disable auto-play',
        'skipQuestionAudio': 'Skip question on replay answer',

        // Advanced tab
        'additional': 'Additional',
        'fsrs': 'FSRS',
        'maxInterval': 'Maximum interval',
        'startingEase': 'Starting ease',
        'easyBonus': 'Easy bonus',
        'intervalModifier': 'Interval modifier',
        'hardInterval': 'Hard interval',
        'newInterval': 'New interval',
        'specialScheduling': 'Special scheduling',

        // Session complete modal
        'reviewCompleted': 'Review Completed!',
        'wellDone': 'Well done!',
        'greatJobMastering': 'Great job! You\'re mastering these words.',
        'sessionProgress': 'Session Progress',
        'dayStreak': 'Day Streak',
        'sessionSummary': 'Session Summary',
        'returnToDeck': 'Return to Deck',
        'allDecks': 'All Decks',
        'hard': 'Hard',
        'listen': 'Listen',
        'allDoneForToday': 'Hooray! All done for today.',
        'startExtraSession': 'If you want to study outside the schedule, start an extra session.',
        'extraSession': 'extra session',
        'noCards': 'No cards to review'
      },
      ru: {
        // Navigation
        'decks': 'Колоды',
        'statistics': 'Статистика',
        'backToDecks': 'Назад к колодам',

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
        'noActivityDescription': 'Вы еще не изучали карточки. Начните обучение, чтобы увидеть свой прогресс здесь.',

        // Deck detail page
        'word': 'Слово',
        'translation': 'Перевод',
        'interval': 'Интервал',
        'repetitions': 'Повторения',
        'nextReview': 'Следующее повторение',
        'actions': 'Действия',
        'addWords': 'Добавить слова',
        'cardsToStudy': 'Карточки для изучения',
        'wordsInDeck': 'Слова в колоде',
        'learning': 'Изучаемые',
        'review': 'Повторение',
        'startReview': 'Начать повторение',
        'noCardsAvailable': 'Нет карточек для повторения в данный момент.',
        'mastered': 'Изучено',
        'today': 'Сегодня',
        'noWordsInDeck': 'В этой колоде пока нет слов',
        'addWordsToBegin': 'Добавьте слова, чтобы начать изучение с этой колодой',

        // Deck actions
        'editDeck': 'Редактировать колоду',
        'deckSettings': 'Настройки колоды',
        'deleteDeck': 'Удалить колоду',
        'moveCard': 'Переместить карточку',
        'resetProgress': 'Сбросить прогресс',
        'removeFromDeck': 'Удалить из колоды',

        // Add word modal
        'addWordsToDeck': 'Добавить слова в колоду',
        'selectWordStatus': 'Выберите статус слов для добавления:',
        'newWords': 'Новые слова',
        'queuedWords': 'В очереди',
        'activeWords': 'Активные слова',
        'learnedWords': 'Изученные слова',
        'searchWordPlaceholder': 'Поиск по слову или переводу...',
        'loadingWords': 'Загрузка слов...',
        'addSelected': 'Добавить выбранные',

        // Edit deck modal
        'description': 'Описание',
        'enterDeckDescription': 'Введите описание колоды',
        'saveChanges': 'Сохранить изменения',

        // Delete deck modal
        'warning': 'Внимание:',
        'actionCannotBeUndone': 'Это действие нельзя отменить.',
        'areYouSureDelete': 'Вы уверены, что хотите удалить колоду',
        'allCardsRemoved': 'Все карточки в этой колоде будут удалены.',
        'delete': 'Удалить',

        // Move card modal
        'selectTargetDeck': 'Выберите целевую колоду для перемещения карточки:',
        'loadingDecks': 'Загрузка колод...',

        // Deck settings modal
        'dailyLimits': 'Дневные лимиты',
        'newCardsPerDay': 'Новых карточек в день',
        'preset': 'Предустановка',
        'thisDeck': 'Эта колода',
        'todayOnly': 'Только сегодня',
        'maxReviewsPerDay': 'Максимум повторяемых в день',
        'reviewLimitNoAffectNew': 'Лимит повторений не влияет на новые',
        'limitsStartFromTop': 'Лимиты начинаются сверху',
        'globalSetting': 'Глобальная настройка',

        // New cards tab
        'newCards': 'Новые карточки',
        'learningSteps': 'Шаги изучаемых',
        'graduatingInterval': 'Интервал перевода',
        'easyInterval': 'Интервал лёгких',
        'insertionOrder': 'Порядок добавления',
        'sequential': 'Последовательный (сначала старые)',
        'random': 'Случайный',

        // Forgotten tab
        'forgotten': 'Забытые',
        'relearningSteps': 'Шаги переучиваемых',
        'minimumInterval': 'Минимальный интервал',
        'lapseThreshold': 'Порог для приставучих',
        'lapseAction': 'Что делать с приставучими',
        'tagOnly': 'Только пометить',
        'suspend': 'Приостановить',

        // Order tab
        'orderDisplay': 'Порядок показа',
        'newCardGathering': 'Порядок отбора новых',
        'byDeck': 'По колоде',
        'newCardOrder': 'Порядок новых',
        'byCardType': 'По типу карточки',
        'byTimeAdded': 'По времени добавления',
        'newAndReviewOrder': 'Порядок новых и повторяемых',
        'interleaveWithReviews': 'Перемежать с повторяемыми',
        'newFirst': 'Сначала новые',
        'reviewFirst': 'Сначала повторяемые',
        'interDayLearningOrder': 'Порядок перенесённых',
        'byDue': 'По сроку',
        'reviewOrder': 'Порядок повторяемых',
        'dueThenRandom': 'По сроку, потом случайный',
        'strictlyByDue': 'Строго по сроку',
        'burying': 'Откладывание',
        'buryNewRelated': 'Откладывать новые связанные до завтра',
        'buryReviewsRelated': 'Откладывать повторяемые связанные до завтра',
        'buryInterday': 'Откладывать связанные изучаемые, которые переносятся',

        // Timer tab
        'timer': 'Таймер',
        'maxAnswerTime': 'Максимум секунд для ответа',
        'showAnswerTimer': 'Показывать время ответа',
        'stopTimerOnAnswer': 'Остановить таймер при ответе',
        'autoPreview': 'Автопросмотр',
        'secondsShowQuestion': 'Секунд для показа вопроса',
        'secondsShowAnswer': 'Секунд для показа ответа',
        'waitForAudio': 'Ждать аудио',
        'answerAction': 'Действие при ответе',
        'buryCard': 'Отложить карточку',
        'again': 'Снова',
        'good': 'Хорошо',
        'easy': 'Легко',

        // Audio tab
        'audio': 'Звук',
        'disableAutoPlay': 'Не воспроизводить звук автоматически',
        'skipQuestionAudio': 'Пропускать вопрос при воспроизведении ответа',

        // Advanced tab
        'additional': 'Дополнительные',
        'fsrs': 'FSRS',
        'maxInterval': 'Максимальный интервал',
        'startingEase': 'Начальная лёгкость',
        'easyBonus': 'Множитель для «Легко»',
        'intervalModifier': 'Модификатор интервала',
        'hardInterval': 'Интервал для «Трудно»',
        'newInterval': 'Новый интервал',
        'specialScheduling': 'Особое планирование',

        // Session complete modal
        'reviewCompleted': 'Повторение завершено!',
        'wellDone': 'Отлично!',
        'greatJobMastering': 'Молодец! Вы осваиваете эти слова.',
        'sessionProgress': 'Прогресс сессии',
        'dayStreak': 'Дней подряд',
        'sessionSummary': 'Итоги сессии',
        'returnToDeck': 'Вернуться к колоде',
        'allDecks': 'Все колоды',
        'hard': 'Трудно',
        'listen': 'Прослушать',
        'allDoneForToday': 'Ура! На сегодня всё.',
        'startExtraSession': 'Если вы хотите заниматься вне расписания, начните допзанятие.',
        'extraSession': 'допзанятие',
        'noCards': 'Нет карточек для повторения'
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

    // Set HTML lang attribute
    document.documentElement.lang = this.currentLang;

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

    // Apply to deck title
    const deckTitle = document.querySelector('.deck-title');
    if (deckTitle && deckTitle.dataset.i18n) {
      deckTitle.textContent = this.translate(deckTitle.dataset.i18n);
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

    // Translate back link
    const backLink = document.querySelector('.back-link span');
    if (backLink) {
      backLink.textContent = this.translate('backToDecks');
    }

    // Translate buttons
    const addWordsBtn = document.querySelector('.add-words-btn span');
    if (addWordsBtn) {
      addWordsBtn.textContent = this.translate('addWords');
    }

    // Translate actions dropdown
    const actionsBtn = document.querySelector('#actionMenuButton .d-none');
    if (actionsBtn) {
      actionsBtn.textContent = this.translate('actions');
    }

    // Special handling for specific elements
    this.updateTableHeaders();
    this.updateEmptyState();
    this.updateDeckDetailElements();
    this.updateModals();
    this.updateButtons();
    this.updateStatisticsElements();
    this.updateSessionCompleteModal();
    this.updateNoCardsMessage();
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

    // Translate table headers in deck detail
    const tableHeaders = {
      'Word': 'word',
      'Translation': 'translation',
      'Interval': 'interval',
      'Repetitions': 'repetitions',
      'Next Review': 'nextReview',
      'Actions': 'actions'
    };

    document.querySelectorAll('th').forEach(th => {
      const text = th.textContent.trim();
      if (tableHeaders[text]) {
        th.textContent = this.translate(tableHeaders[text]);
      }
    });

    // Translate "day" and "days" in interval column
    document.querySelectorAll('td').forEach(td => {
      if (td.innerHTML.includes('day</span>')) {
        td.innerHTML = td.innerHTML.replace('day</span>', this.translate('day') + '</span>');
      } else if (td.innerHTML.includes('days</span>')) {
        td.innerHTML = td.innerHTML.replace('days</span>', this.translate('days') + '</span>');
      }
    });
  }

  /**
   * Update deck detail specific elements
   */
  updateDeckDetailElements() {
    // Card Counter Labels
    document.querySelectorAll('.counter-label').forEach(label => {
      const text = label.textContent.trim();
      if (text === 'New') {
        label.textContent = this.translate('new');
      } else if (text === 'Learning') {
        label.textContent = this.translate('learning');
      } else if (text === 'Review') {
        label.textContent = this.translate('review');
      }
    });

    // Study progress title
    const studyProgressTitle = document.querySelector('#study-progress-title');
    if (studyProgressTitle) {
      studyProgressTitle.textContent = this.translate('cardsToStudy');
    }

    // Words in deck title
    const wordsListTitle = document.querySelector('#cards-list-title');
    if (wordsListTitle) {
      wordsListTitle.textContent = this.translate('wordsInDeck');
    }

    // Start review button
    const startReviewBtn = document.querySelector('.start-review-btn');
    if (startReviewBtn) {
      const icon = '<i class="bi bi-play-fill me-2"></i> ';
      startReviewBtn.innerHTML = icon + this.translate('startReview');
    }

    // No cards alert
    const alertInfo = document.querySelector('.alert-info');
    if (alertInfo && alertInfo.textContent.includes('No cards available')) {
      const icon = '<i class="bi bi-info-circle me-2"></i> ';
      alertInfo.innerHTML = icon + this.translate('noCardsAvailable');
    }

    // Badges
    document.querySelectorAll('.badge').forEach(badge => {
      if (badge.textContent === 'New') {
        badge.textContent = this.translate('new');
      } else if (badge.textContent === 'Today') {
        badge.textContent = this.translate('today');
      }
    });

    // Mastered title
    const masteredIcon = document.querySelector('.text-success');
    if (masteredIcon && masteredIcon.title === 'Mastered') {
      masteredIcon.title = this.translate('mastered');
    }

    // No words in deck empty state
    const emptyStateTitle = document.querySelector('.empty-state-title');
    if (emptyStateTitle && emptyStateTitle.textContent.includes('There are no words')) {
      emptyStateTitle.textContent = this.translate('noWordsInDeck');
    }

    const emptyStateDesc = document.querySelector('.empty-state-description');
    if (emptyStateDesc && emptyStateDesc.textContent.includes('Add words to begin')) {
      emptyStateDesc.textContent = this.translate('addWordsToBegin');
    }

    // Dropdown items
    document.querySelectorAll('.dropdown-item').forEach(item => {
      if (item.textContent.includes('Edit Deck')) {
        item.innerHTML = '<i class="bi bi-pencil me-2"></i> ' + this.translate('editDeck');
      } else if (item.textContent.includes('Deck Settings')) {
        item.innerHTML = '<i class="bi bi-gear me-2"></i> ' + this.translate('deckSettings');
      } else if (item.textContent.includes('Delete Deck')) {
        item.innerHTML = '<i class="bi bi-trash me-2"></i> ' + this.translate('deleteDeck');
      } else if (item.textContent.includes('Move Card')) {
        item.innerHTML = '<i class="bi bi-arrow-left-right me-2"></i> ' + this.translate('moveCard');
      } else if (item.textContent.includes('Reset Progress')) {
        item.innerHTML = '<i class="bi bi-arrow-counterclockwise me-2"></i> ' + this.translate('resetProgress');
      } else if (item.textContent.includes('Remove from Deck')) {
        item.innerHTML = '<i class="bi bi-x-lg me-2"></i> ' + this.translate('removeFromDeck');
      }
    });

    // Actions button for cards
    document.querySelectorAll('.card-actions-dropdown button').forEach(btn => {
      if (btn.textContent.trim() === 'Actions') {
        btn.textContent = this.translate('actions');
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

    // Update Add Words button
    const addWordsBtn = document.querySelector('.btn-sm[data-bs-toggle="modal"][data-bs-target="#addWordModal"]');
    if (addWordsBtn) {
      const addIcon = '<i class="bi bi-plus-lg me-1"></i> ';
      addWordsBtn.innerHTML = addIcon + this.translate('addWords');
    }

    // Empty state Add Words button
    const emptyStateAddBtn = document.querySelector('.empty-state .btn-primary');
    if (emptyStateAddBtn && emptyStateAddBtn.textContent.includes('Add Words')) {
      const addIcon = '<i class="bi bi-plus-lg me-2"></i> ';
      emptyStateAddBtn.innerHTML = addIcon + this.translate('addWords');
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
        if (option.value === '7') {
          option.textContent = this.translate('lastSevenDays');
        } else if (option.value === '14') {
          option.textContent = this.translate('lastFourteenDays');
        } else if (option.value === '30') {
          option.textContent = this.translate('lastThirtyDays');
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
    // Add Words modal
    const addWordModalLabel = document.querySelector('#addWordModalLabel');
    if (addWordModalLabel) {
      addWordModalLabel.textContent = this.translate('addWordsToDeck');
    }

    // Select word status text
    const selectStatusText = document.querySelector('#addWordModal p');
    if (selectStatusText && selectStatusText.textContent.trim() === 'Select word status to add:') {
      selectStatusText.textContent = this.translate('selectWordStatus');
    }

    // Word status options
    const wordStatusSelect = document.querySelector('#wordStatusSelect');
    if (wordStatusSelect) {
      Array.from(wordStatusSelect.options).forEach(option => {
        if (option.textContent === 'New Words') {
          option.textContent = this.translate('newWords');
        } else if (option.textContent === 'Queued Words') {
          option.textContent = this.translate('queuedWords');
        } else if (option.textContent === 'Active Words') {
          option.textContent = this.translate('activeWords');
        } else if (option.textContent === 'Learned Words') {
          option.textContent = this.translate('learnedWords');
        }
      });
    }

    // Search placeholder
    const searchInput = document.querySelector('#wordSearchInput');
    if (searchInput && searchInput.placeholder === 'Search by word or translation...') {
      searchInput.placeholder = this.translate('searchWordPlaceholder');
    }

    // Loading text
    const loadingText = document.querySelector('#wordsLoadingRow .ms-2');
    if (loadingText && loadingText.textContent === 'Loading words...') {
      loadingText.textContent = this.translate('loadingWords');
    }

    // Edit Deck modal
    const editDeckModalLabel = document.querySelector('#editDeckModalLabel');
    if (editDeckModalLabel) {
      editDeckModalLabel.textContent = this.translate('editDeck');
    }

    // Deck Name label
    const deckNameLabel = document.querySelector('label[for="deckNameInput"]');
    if (deckNameLabel) {
      deckNameLabel.textContent = this.translate('deckName');
    }

    // Description label
    const descriptionLabel = document.querySelector('label[for="deckDescriptionInput"]');
    if (descriptionLabel) {
      descriptionLabel.textContent = this.translate('description');
    }

    // Description placeholder
    const descriptionInput = document.querySelector('#deckDescriptionInput');
    if (descriptionInput && descriptionInput.placeholder === 'Enter deck description') {
      descriptionInput.placeholder = this.translate('enterDeckDescription');
    }

    // Delete Deck modal
    const deleteDeckModalLabel = document.querySelector('#deleteDeckModalLabel');
    if (deleteDeckModalLabel) {
      deleteDeckModalLabel.textContent = this.translate('deleteDeck');
    }

    // Warning text
    const warningText = document.querySelector('.alert-danger strong');
    if (warningText && warningText.textContent === 'Warning:') {
      warningText.textContent = this.translate('warning') + ':';
    }

    // Cannot be undone text
    const alertText = document.querySelector('.alert-danger');
    if (alertText && alertText.textContent.includes('This action cannot be undone')) {
      const icon = '<i class="bi bi-exclamation-triangle-fill me-2"></i> ';
      const strongTag = '<strong>' + this.translate('warning') + ':</strong> ';
      alertText.innerHTML = icon + strongTag + this.translate('actionCannotBeUndone');
    }

    // Are you sure text and All cards will be removed
    const deleteConfirmParagraphs = document.querySelectorAll('#deleteDeckModal .modal-body p:not(.alert)');
    if (deleteConfirmParagraphs.length >= 2) {
      if (deleteConfirmParagraphs[0].textContent.includes('Are you sure')) {
        // Keep the deck name in the confirmation text
        const deckName = deleteConfirmParagraphs[0].querySelector('strong').textContent;
        deleteConfirmParagraphs[0].innerHTML = this.translate('areYouSureDelete') + ' <strong>' + deckName + '</strong>?';
      }
      if (deleteConfirmParagraphs[1].textContent.includes('All cards in this deck')) {
        deleteConfirmParagraphs[1].textContent = this.translate('allCardsRemoved');
      }
    }

    // Move Card modal
    const moveCardModalLabel = document.querySelector('#moveCardModalLabel');
    if (moveCardModalLabel) {
      moveCardModalLabel.textContent = this.translate('moveCard');
    }

    // Select target deck text
    const selectTargetText = document.querySelector('#moveCardModal p');
    if (selectTargetText && selectTargetText.textContent.includes('Select the target deck')) {
      selectTargetText.textContent = this.translate('selectTargetDeck');
    }

    // Loading decks option
    const loadingDecksOption = document.querySelector('#targetDeckSelect option');
    if (loadingDecksOption && loadingDecksOption.textContent === 'Loading decks...') {
      loadingDecksOption.textContent = this.translate('loadingDecks');
    }

    // Translation of all settings tabs
    const settingsTabs = {
      'daily-tab': 'dailyLimits',
      'new-cards-tab': 'newCards',
      'forgotten-tab': 'forgotten',
      'order-tab': 'orderDisplay',
      'timer-tab': 'timer',
      'audio-tab': 'audio',
      'advanced-tab': 'additional'
    };

    Object.entries(settingsTabs).forEach(([id, key]) => {
      const tab = document.querySelector(`#${id}`);
      if (tab) {
        tab.textContent = this.translate(key);
      }
    });

    // Update buttons
    const modalCancelBtns = document.querySelectorAll('.modal-footer .btn-secondary');
    modalCancelBtns.forEach(btn => {
      if (btn.textContent === 'Cancel') {
        btn.textContent = this.translate('cancel');
      }
    });

    const saveBtn = document.querySelector('#saveDeckBtn');
    if (saveBtn) {
      const saveIcon = '<i class="bi bi-save me-1"></i> ';
      saveBtn.innerHTML = saveIcon + this.translate('saveChanges');
    }

    const saveDeckSettingsBtn = document.querySelector('#saveDeckSettingsBtn');
    if (saveDeckSettingsBtn) {
      const saveIcon = '<i class="bi bi-save me-1"></i> ';
      saveDeckSettingsBtn.innerHTML = saveIcon + this.translate('saveChanges');
    }

    const confirmDeleteBtn = document.querySelector('#confirmDeleteDeckBtn');
    if (confirmDeleteBtn) {
      const deleteIcon = '<i class="bi bi-trash me-1"></i> ';
      confirmDeleteBtn.innerHTML = deleteIcon + this.translate('delete');
    }

    const confirmMoveCardBtn = document.querySelector('#confirmMoveCardBtn');
    if (confirmMoveCardBtn) {
      const moveIcon = '<i class="bi bi-arrow-left-right me-1"></i> ';
      confirmMoveCardBtn.innerHTML = moveIcon + this.translate('moveCard');
    }

    const addSelectedBtn = document.querySelector('#addSelectedWordsBtn');
    if (addSelectedBtn) {
      const addIcon = '<i class="bi bi-plus-lg me-1"></i> ';
      addSelectedBtn.innerHTML = addIcon + this.translate('addSelected');
    }
  }

  /**
   * Update session complete modal content
   */
  updateSessionCompleteModal() {
    // Modal title
    const modalTitle = document.querySelector('#sessionCompleteModalLabel');
    if (modalTitle) {
      modalTitle.textContent = this.translate('reviewCompleted');
    }

    // Session complete title
    const sessionCompleteTitle = document.querySelector('#sessionCompleteTitle');
    if (sessionCompleteTitle) {
      sessionCompleteTitle.textContent = this.translate('wellDone');
    }

    // Session complete message
    const sessionCompleteMessage = document.querySelector('#sessionCompleteMessage');
    if (sessionCompleteMessage) {
      // Проверяем содержимое, чтобы определить, какое сообщение показывать
      if (sessionCompleteMessage.textContent.includes('mastering these words')) {
        sessionCompleteMessage.textContent = this.translate('greatJobMastering');
      } else {
        // Другие возможные сообщения можно добавить здесь
        sessionCompleteMessage.textContent = this.translate(sessionCompleteMessage.textContent);
      }
    }

    // Cards reviewed label
    const cardsReviewedLabel = document.querySelector('.col-6:first-child .text-muted');
    if (cardsReviewedLabel) {
      cardsReviewedLabel.textContent = this.translate('cardsReviewed');
    }

    // Day streak label
    const dayStreakLabel = document.querySelector('.col-6:last-child .text-muted');
    if (dayStreakLabel) {
      dayStreakLabel.textContent = this.translate('dayStreak');
    }

    // Return to deck button
    const returnToDeckBtn = document.querySelector('.modal-footer a.btn-primary');
    if (returnToDeckBtn) {
      returnToDeckBtn.textContent = this.translate('returnToDeck');
    }

    // All decks button
    const allDecksBtn = document.querySelector('.modal-footer a.btn-secondary');
    if (allDecksBtn) {
      allDecksBtn.textContent = this.translate('allDecks');
    }
  }

  updateNoCardsMessage() {
    // Обновляем заголовок сообщения
    const noCardsTitle = document.querySelector('.no-cards-title');
    if (noCardsTitle) {
      noCardsTitle.textContent = this.translate('allDoneForToday');
    }

    // Обновляем текст сообщения, сохраняя ссылку
    const noCardsText = document.querySelector('.no-cards-text');
    if (noCardsText) {
      // Получаем ссылку и её содержимое
      const extraSessionLink = noCardsText.querySelector('.extra-session-link');
      if (extraSessionLink) {
        // Получаем перевод для текста ссылки
        const extraSessionText = this.translate('extraSession');
        const linkSpan = extraSessionLink.querySelector('span');
        if (linkSpan) {
          linkSpan.textContent = extraSessionText;
        }

        // Полный текст сообщения
        const startExtraSessionText = this.translate('startExtraSession');

        // Находим позицию текста "допзанятие" в переводе
        const linkTextPosition = startExtraSessionText.indexOf(extraSessionText);

        if (linkTextPosition !== -1) {
          // Разделяем текст на части: до ссылки и после ссылки
          const textBeforeLink = startExtraSessionText.substring(0, linkTextPosition);
          const textAfterLink = startExtraSessionText.substring(linkTextPosition + extraSessionText.length);

          // Формируем новый HTML для текста с сохранением ссылки
          noCardsText.innerHTML = textBeforeLink;
          noCardsText.appendChild(extraSessionLink.cloneNode(true));
          noCardsText.innerHTML += textAfterLink;
        } else {
          // Если шаблон текста не совпадает, просто обновляем весь текст
          noCardsText.innerHTML = startExtraSessionText.replace(
            extraSessionText,
            `<a href="${extraSessionLink.getAttribute('href')}" class="extra-session-link"><span data-i18n="extraSession">${extraSessionText}</span></a>`
          );
        }
      } else {
        // Если ссылки нет, просто обновляем текст
        noCardsText.textContent = this.translate('startExtraSession');
      }
    }
  }
}

// Export for use in main app
export { LanguageManager };