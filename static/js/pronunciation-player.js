/**
 * Универсальный проигрыватель произношения
 * С исправлениями и дополнительной отладкой
 */

// Создаем глобальный объект для управления воспроизведением
window.pronunciationPlayer = {
  // Кэш для аудио-элементов
  audioCache: {},

  // Текущий воспроизводимый элемент
  currentAudio: null,

  // Состояние загрузки для каждого слова
  loadingState: {},

  // Определяем тип страницы
  pageType: null,

  // Базовый URL для аудиофайлов (используем функцию для динамического определения)
  getBaseUrl: function() {
    // Пытаемся найти существующий аудио-элемент на странице, чтобы извлечь правильный путь
    const audioElements = document.querySelectorAll('audio[src*="pronunciation_en_"]');
    if (audioElements.length > 0) {
      const src = audioElements[0].querySelector('source')?.getAttribute('src') ||
                  audioElements[0].getAttribute('src');
      if (src) {
        // Извлекаем путь до "pronunciation_en_"
        const match = src.match(/(.*pronunciation_en_)[^.]+\.mp3/);
        if (match && match[1]) {
          return match[1];
        }
      }
    }

    // Определяем URL по умолчанию на основе домена
    const origin = window.location.origin;
    const basePath = '/static/media/pronunciation_en_';
    return origin + basePath;
  },

  /**
   * Инициализирует плеер и подключает обработчики событий
   */
  init: function() {
    // Определяем тип страницы
    this.pageType = this.detectPageType();

    // На странице деталей слова не перехватываем события,
    // так как там уже есть свой плеер
    if (this.pageType === 'word_detail') {
      return;
    }

    // Добавляем глобальный обработчик для кнопок воспроизведения
    document.addEventListener('click', function(e) {
      // Находим ближайшую кнопку воспроизведения
      const button = e.target.closest('.play-pronunciation');
      if (!button) return;

      // Предотвращаем дальнейшее распространение события только если кнопка не отключена
      if (button.disabled) {
        return;
      }

      e.preventDefault();
      e.stopPropagation();

      // Получаем слово для воспроизведения
      const word = button.getAttribute('data-word');
      if (!word) return;

      // Воспроизводим слово
      pronunciationPlayer.play(word);
    }, true); // Используем фазу перехвата для обработки события до других обработчиков

    // Тестовое воспроизведение пустого звука для разблокировки аудио API
    this.unlockAudio();
  },

  /**
   * Разблокировать аудио API в браузере после взаимодействия пользователя
   */
  unlockAudio: function() {
    // Создаем тихий звук для разблокировки аудио API
    const unlockAudio = document.createElement('audio');
    unlockAudio.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
    unlockAudio.volume = 0.01; // Очень тихо

    // Пытаемся воспроизвести его после первого взаимодействия с страницей
    const unlockFn = function() {
      unlockAudio.play().then(() => {
      }).catch(e => {
      });

      // Убираем обработчики после первого вызова
      document.removeEventListener('click', unlockFn);
      document.removeEventListener('touchstart', unlockFn);
      document.removeEventListener('keydown', unlockFn);
    };

    document.addEventListener('click', unlockFn, { once: true });
    document.addEventListener('touchstart', unlockFn, { once: true });
    document.addEventListener('keydown', unlockFn, { once: true });
  },

  /**
   * Определяет тип текущей страницы
   * @returns {string} Тип страницы: 'word_detail', 'words_list' или 'other'
   */
  detectPageType: function() {
    // Проверяем характерные элементы для страниц
    const hasAudioContainer = document.getElementById('audioContainer') !== null;
    const hasAudioPlayer = document.getElementById('audioPlayBtn') !== null;
    const hasWordsTable = document.querySelector('.words-table') !== null;

    // Проверка на страницу деталей слова
    if (hasAudioContainer && hasAudioPlayer && !hasWordsTable) {
      return 'word_detail';
    }
    // Проверка на страницу списка слов
    else if (hasWordsTable || document.querySelector('.play-pronunciation')) {
      return 'words_list';
    }

    // По умолчанию
    return 'other';
  },

  /**
   * Воспроизводит произношение для указанного слова
   * @param {string} word - Слово для воспроизведения
   */
  play: function(word) {
    if (!word) return;

    // На странице деталей слова используем встроенный плеер
    if (this.pageType === 'word_detail') {
      return;
    }

    // Останавливаем текущее воспроизведение, если есть
    this.stopCurrentAudio();

    // Формируем путь к аудиофайлу
    const audioKey = word.toLowerCase();
    const audioPath = this.getAudioPath(audioKey);

    // Проверяем, есть ли уже загруженный аудио-элемент
    if (this.audioCache[audioKey]) {
      const audio = this.audioCache[audioKey];
      this.currentAudio = audio;

      // Воспроизводим аудио
      this.playAudio(audio);
      return;
    }

    // Если аудио уже загружается, не дублируем запрос
    if (this.loadingState[audioKey]) {
      return;
    }

    // Добавляем индикацию загрузки ко всем кнопкам данного слова
    this.setButtonsLoading(word, true);

    // Создаем новый аудио-элемент
    const audio = new Audio();


    // Устанавливаем флаг загрузки
    this.loadingState[audioKey] = true;

    // Обработчик события загрузки
    audio.addEventListener('canplaythrough', () => {
      this.loadingState[audioKey] = false;
      this.audioCache[audioKey] = audio;

      // Убираем индикацию загрузки
      this.setButtonsLoading(word, false);

      // Если это текущий аудио-элемент, воспроизводим его
      if (this.currentAudio === audio) {
        this.playAudio(audio);
      }
    });

    // Обработчик ошибки
    audio.addEventListener('error', (e) => {
      const errorCode = audio.error ? audio.error.code : 'нет кода';
      const errorMessage = audio.error ? audio.error.message : 'нет сообщения';
      console.error(`Ошибка загрузки аудио для слова "${word}": код ${errorCode}, ${errorMessage}`);

      this.loadingState[audioKey] = false;

      // Удаляем из кэша, если была ошибка
      delete this.audioCache[audioKey];

      // Убираем индикацию загрузки
      this.setButtonsLoading(word, false);

      // Уведомляем пользователя об ошибке
      this.showError(word);

      // Пробуем альтернативный URL, если текущий был по умолчанию
      if (!audioPath.includes('/serve_media/')) {
        this.tryAlternativeUrl(word);
      }
    });

    // Устанавливаем источник аудио
    audio.src = audioPath;

    // Сохраняем текущий аудио-элемент
    this.currentAudio = audio;

    // Начинаем загрузку
    audio.load();
  },

  /**
   * Пробует альтернативный URL-путь для аудиофайла
   * @param {string} word - Слово для воспроизведения
   */
  tryAlternativeUrl: function(word) {

    // Попробуем использовать маршрут serve_media
    const audioKey = word.toLowerCase();
    const formattedWord = audioKey.replace(/\s+/g, '_');
    const alternativeUrl = `/serve_media/pronunciation_en_${formattedWord}.mp3`;


    const audio = new Audio();
    audio.addEventListener('canplaythrough', () => {
      this.audioCache[audioKey] = audio;
      this.currentAudio = audio;
      this.playAudio(audio);

      // Обновим базовый URL для будущих запросов
      this._baseUrl = `/serve_media/pronunciation_en_`;
    });

    audio.addEventListener('error', () => {
      console.error(`Альтернативный URL тоже не работает для слова "${word}"`);
    });

    audio.src = alternativeUrl;
    audio.load();
  },

  /**
   * Формирует путь к аудиофайлу
   * @param {string} word - Слово
   * @returns {string} - Путь к аудиофайлу
   */
  getAudioPath: function(word) {
    // Подготавливаем слово для URL (заменяем пробелы на подчеркивания)
    const formattedWord = word.replace(/\s+/g, '_');

    // Используем кэшированный базовый URL или получаем новый
    if (!this._baseUrl) {
      this._baseUrl = this.getBaseUrl();
    }

    // Формируем путь к аудиофайлу
    return this._baseUrl + formattedWord + '.mp3';
  },

  /**
   * Устанавливает состояние загрузки для кнопок
   * @param {string} word - Слово
   * @param {boolean} isLoading - Состояние загрузки
   */
  setButtonsLoading: function(word, isLoading) {
    const buttons = document.querySelectorAll(`.play-pronunciation[data-word="${word}"]`);

    buttons.forEach(button => {
      if (isLoading) {
        // Добавляем класс загрузки
        button.classList.add('loading');

        // Меняем иконку на спиннер, если есть
        if (button.querySelector('i')) {
          button.querySelector('i').className = 'bi bi-arrow-repeat';
        }
      } else {
        // Убираем класс загрузки
        button.classList.remove('loading');

        // Возвращаем нормальную иконку
        if (button.querySelector('i')) {
          button.querySelector('i').className = 'bi bi-volume-up';
        }
      }
    });
  },

  /**
   * Воспроизводит аудио-элемент с полной отладкой
   * @param {HTMLAudioElement} audio - Аудио-элемент для воспроизведения
   */
  playAudio: function(audio) {
    if (!audio) return;

    // Убедимся, что аудио не отключено
    audio.muted = false;
    audio.volume = 1.0;

    // Сбрасываем аудио на начало
    audio.currentTime = 0;

    try {
      const playPromise = audio.play();

      // Обрабатываем случай, когда браузер возвращает Promise
      if (playPromise !== undefined) {
        playPromise.then(() => {
        }).catch(error => {

          // Показываем сообщение пользователю
          this.showPlaybackError();

          // Пробуем воспроизвести через Web Audio API как запасной вариант
          this.playWithWebAudio(audio);
        });
      } else {
      }
    } catch (e) {

      // Показываем сообщение пользователю
      this.showPlaybackError();

      // Пробуем воспроизвести через Web Audio API как запасной вариант
      this.playWithWebAudio(audio);
    }
  },

  /**
   * Воспроизводит аудио через Web Audio API как запасной вариант
   * @param {HTMLAudioElement} audio - Аудио-элемент для воспроизведения
   */
  playWithWebAudio: function(audio) {
    if (!audio.src) return;


    // Создаем AudioContext, если его еще нет
    if (!this.audioContext) {
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioContext();
      } catch (e) {
        console.error('Web Audio API не поддерживается:', e);
        return;
      }
    }

    // Создаем новый запрос для загрузки аудиофайла напрямую
    fetch(audio.src)
      .then(response => {
        if (!response.ok) {
          throw new Error('Сетевой ответ не был успешным');
        }
        return response.arrayBuffer();
      })
      .then(arrayBuffer => this.audioContext.decodeAudioData(arrayBuffer))
      .then(audioBuffer => {
        // Создаем источник звука
        const source = this.audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.audioContext.destination);

        // Воспроизводим
        source.start(0);
      })
      .catch(error => {
      });
  },

  /**
   * Останавливает текущее воспроизведение
   */
  stopCurrentAudio: function() {
    if (this.currentAudio) {
      try {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
      } catch (e) {
      }
    }
  },

  /**
   * Показывает сообщение об ошибке загрузки
   * @param {string} word - Слово, для которого произошла ошибка
   */
  showError: function(word) {
    // Находим все кнопки для этого слова
    const buttons = document.querySelectorAll(`.play-pronunciation[data-word="${word}"]`);

    buttons.forEach(button => {
      // Меняем иконку на "ошибка"
      if (button.querySelector('i')) {
        button.querySelector('i').className = 'bi bi-exclamation-triangle';
      }

      // Добавляем класс ошибки
      button.classList.add('error');

      // Устанавливаем tooltip с ошибкой
      button.setAttribute('title', 'Error loading pronunciation');

      // Возвращаем нормальную иконку через 3 секунды
      setTimeout(() => {
        if (button.querySelector('i')) {
          button.querySelector('i').className = 'bi bi-volume-up';
        }
        button.classList.remove('error');
      }, 3000);
    });
  },

  /**
   * Показывает сообщение об ошибке воспроизведения
   */
  showPlaybackError: function() {
    // Проверяем, есть ли контейнер для уведомлений
    let toastContainer = document.querySelector('.toast-container');

    // Создаем контейнер, если его нет
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      document.body.appendChild(toastContainer);
    }

    // Создаем уведомление
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white bg-warning border-0';
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">
          <i class="bi bi-volume-mute me-2"></i>
          Browser blocked audio playback. Click anywhere to enable audio.
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;

    // Добавляем в контейнер
    toastContainer.appendChild(toast);

    // Инициализируем и показываем toast
    try {
      const bsToast = new bootstrap.Toast(toast, {
        delay: 5000,
        autohide: true
      });

      bsToast.show();

      // Удаляем toast после того, как он будет скрыт
      toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
      });
    } catch (e) {
      // Если Bootstrap не доступен, используем простую анимацию
      toast.style.opacity = '1';
      toast.style.transition = 'opacity 0.5s';

      setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
      }, 5000);
    }
  }
};

// Инициализируем плеер после загрузки DOM
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function() {
    pronunciationPlayer.init();
  });
} else {
  pronunciationPlayer.init();
}

// Добавляем также обработчик события взаимодействия с страницей для разблокировки аудио API
document.addEventListener('click', function() {
  if (window.pronunciationPlayer) {
    window.pronunciationPlayer.unlockAudio();
  }
}, { once: true });

// Делаем доступной простую функцию воспроизведения для вызова из других скриптов
function playPronunciation(word) {
  if (window.pronunciationPlayer) {
    // Только если не на странице деталей слова
    if (window.pronunciationPlayer.pageType !== 'word_detail') {
      window.pronunciationPlayer.play(word);
      return true;
    }
  }
  return false;
}

// Экспортируем функцию в глобальную область видимости
window.playPronunciation = playPronunciation;