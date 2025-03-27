/**
 * Инициализация языкового менеджера
 * Этот файл должен загружаться последним в списке скриптов
 */

// Проверяем, что DOM полностью загружен
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLanguageWhenSafe);
} else {
  // DOM уже загружен, нужно дождаться загрузки всех скриптов
  window.addEventListener('load', function() {
    setTimeout(initLanguageWhenSafe, 500);
  });
}

/**
 * Инициализирует языковой менеджер, когда это безопасно
 */
function initLanguageWhenSafe() {
  try {
    // Теперь инициализируем языковой менеджер
    initLanguageManager();

  } catch(e) {
    console.error('Ошибка при инициализации языкового менеджера:', e);
  }
}

/**
 * Инициализирует языковой менеджер
 */
function initLanguageManager() {

  if (typeof LanguageManager === 'undefined') {
    console.error('LanguageManager не найден. Убедитесь, что language-manager.js загружен.');
    return;
  }

  // Создаем экземпляр менеджера языка
  window.langManager = new LanguageManager();

  // Проверяем, правильно ли установлен язык и добавляем класс к body
  document.body.classList.add('lang-' + window.langManager.currentLang);

  // Добавляем переключатель языка
  addLanguageSwitcher();

  // Проверяем сохраненные настройки языка
  try {
    const storedLang = localStorage.getItem('preferredLanguage');
    if (storedLang && ['en', 'ru'].includes(storedLang)) {
      setLanguage(storedLang);
    }
  } catch (e) {
    console.warn('Ошибка при проверке сохраненного языка:', e);
  }
}

/**
 * Получает обработчики событий элемента (по возможности)
 */
function getEventListeners(element) {
  // Эта функция - заглушка, так как браузеры не предоставляют прямой доступ к eventListeners
  // В реальной ситуации мы не можем получить существующие обработчики
  return null;
}

/**
 * Функция для добавления переключателя языка
 */
function addLanguageSwitcher() {
  // Проверяем, есть ли уже переключатель
  if (document.getElementById('languageSwitcher')) return;

  // Создаем переключатель
  const switcher = document.createElement('div');
  switcher.id = 'languageSwitcher';
  switcher.className = 'language-switcher';
  switcher.innerHTML = `
    <button class="btn btn-sm btn-outline-secondary language-toggle">
      <span class="lang-en-text">RU</span>
      <span class="lang-ru-text">EN</span>
    </button>
  `;

  // Добавляем стили
  const style = document.createElement('style');
  style.textContent = `
    .language-switcher {
      position: fixed;
      top: 10px;
      right: 10px;
      z-index: 1000;
    }
    .lang-en .lang-ru-text, .lang-ru .lang-en-text {
      display: none;
    }
    .language-toggle {
      min-width: 40px;
      border-radius: 20px;
      font-weight: bold;
    }
  `;

  // Добавляем элементы на страницу
  document.head.appendChild(style);
  document.body.appendChild(switcher);
}

/**
 * Функция переключения языка
 */
function toggleLanguage() {
  if (!window.langManager) return;

  const newLang = window.langManager.currentLang === 'en' ? 'ru' : 'en';
  setLanguage(newLang);
}

/**
 * Установка конкретного языка
 */
function setLanguage(lang) {
  if (!window.langManager) return false;

  if (['en', 'ru'].includes(lang)) {
    // Меняем язык
    window.langManager.currentLang = lang;

    // Обновляем классы
    document.documentElement.lang = lang;
    document.body.classList.remove('lang-en', 'lang-ru');
    document.body.classList.add('lang-' + lang);

    // Применяем переводы
    window.langManager.applyTranslations();

    // Сохраняем предпочтение в localStorage
    try {
      localStorage.setItem('preferredLanguage', lang);
    } catch (e) {
      console.warn('Не удалось сохранить языковые настройки:', e);
    }


    return true;
  } else {
    console.error('Неподдерживаемый язык:', lang);
    return false;
  }
}

// Делаем функции доступными глобально
window.toggleLanguage = toggleLanguage;
window.setLanguage = setLanguage;