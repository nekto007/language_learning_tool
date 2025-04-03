// Файл: static/js/study-guide.js

// Гибкий гид по разделу обучения
class StudyGuide {
  constructor() {
    this.currentTipIndex = 0;
    this.overlayElement = null;
    this.tooltipElement = null;
    this.progressDotsElement = null;
    this.targetElementHighlight = null;
    this.helpButton = null;
    this.isTooltipDragging = false;
    this.tooltipDragStartX = 0;
    this.tooltipDragStartY = 0;

    // Определяем шаги гида
    this.tips = [
      {
        title: "Добро пожаловать в раздел обучения!",
        description: "Это ваша панель управления обучением. Здесь вы можете отслеживать прогресс и начинать новые сессии обучения.",
        targetFinder: () => document.querySelector("h1"),
        position: "bottom"
      },
      {
        title: "Статистика обучения",
        description: "Здесь вы видите слова, ожидающие повторения, общее количество слов и ваш прогресс в изучении словаря.",
        targetFinder: () => document.querySelector(".row.mb-4") || document.querySelector(".card-text.text-primary")?.closest(".card") || document.querySelector(".card-text")?.closest(".card"),
        position: "bottom"
      },
      {
        title: "Начните обучение",
        description: "В этом блоке вы можете настроить и запустить обучение.",
        targetFinder: () => {
          const heading = Array.from(document.querySelectorAll("h5, .card-header")).find(el =>
            el.textContent.includes("Начните занятия") || el.textContent.includes("Start a Study Session")
          );
          return heading ? heading.closest(".card") : document.querySelector(".card.mb-4");
        },
        position: "right"
      },
      {
        title: "Режим обучения",
        description: "Выберите как вы хотите учить слова: карточки (как в Anki), викторина или игра на соответствие.",
        targetFinder: () => document.querySelector("#session_type") || document.querySelector("select"),
        position: "right"
      },
      {
        title: "Источник слов",
        description: "Выберите, какие слова будут в сессии: новые, требующие повторения, сложные или те, что вы добавили в очередь.",
        targetFinder: () => document.querySelector("#word_source") || document.querySelectorAll("select")[1],
        position: "right"
      },
      {
        title: "Количество слов",
        description: "Выберите, сколько слов вы хотите изучить за одну сессию. Рекомендуем начинать с 5-10 слов.",
        targetFinder: () => document.querySelector("#max_words") || document.querySelector("input[type='number']"),
        position: "right"
      },
      {
        title: "Начало сеанса",
        description: "Когда всё настроено, нажмите эту кнопку, чтобы начать обучение.",
        targetFinder: () => document.querySelector("input[type='submit']") || document.querySelector(".btn-primary"),
        position: "bottom"
      },
      {
        title: "Настройки обучения",
        description: "Здесь можно изменить параметры обучения: частоту показа новых слов, включение подсказок и другие опции.",
        targetFinder: () => document.querySelector(".btn-outline-secondary") || document.querySelector("a:not(.btn-primary):not(.btn-outline-primary)"),
        position: "bottom"
      },
      {
        title: "История сессий",
        description: "В этой таблице показаны ваши недавние сессии обучения: тип, количество слов, результат и потраченное время.",
        targetFinder: () => {
          // Ищем по тексту заголовка
          const headings = Array.from(document.querySelectorAll("h5, .card-header"));
          const sessionHeading = headings.find(el =>
            el.textContent.includes("Последние учебные сессии") ||
            el.textContent.includes("Recent Study Sessions") ||
            el.textContent.includes("учебные сессии")
          );
          return sessionHeading ? sessionHeading.closest(".card") : document.querySelector("table")?.closest(".card");
        },
        position: "top"
      },
      {
        title: "Просмотр статистики",
        description: "Чтобы увидеть подробную статистику вашего обучения, нажмите здесь.",
        targetFinder: () => {
          return Array.from(document.querySelectorAll("a")).find(el =>
            el.textContent.includes("Посмотреть всю статистику") ||
            el.textContent.includes("View All Stats")
          );
        },
        position: "bottom"
      },
      {
        title: "Советы для обучения",
        description: "Здесь вы найдете полезные советы, которые помогут вам эффективнее изучать слова.",
        targetFinder: () => {
          // Ищем по тексту заголовка
          const headings = Array.from(document.querySelectorAll("h5, .card-header"));
          const tipsHeading = headings.find(el =>
            el.textContent.includes("Советы по обучению") ||
            el.textContent.includes("Study Tips") ||
            el.textContent.includes("обучению")
          );
          if (tipsHeading) {
            return tipsHeading.closest(".card");
          }
          // Альтернативный поиск
          return document.querySelector(".list-group-item")?.closest(".card");
        },
        position: "left"
      },
      {
        title: "Быстрые действия",
        description: "Эти кнопки позволяют быстро запустить определенные типы сессий без дополнительных настроек.",
        targetFinder: () => {
          // Ищем по тексту заголовка
          const headings = Array.from(document.querySelectorAll("h5, .card-header"));
          const actionsHeading = headings.find(el =>
            el.textContent.includes("Быстрые действия") ||
            el.textContent.includes("Quick Actions")
          );

          if (actionsHeading) {
            return actionsHeading.closest(".card");
          }

          // Альтернативный поиск - последняя карточка
          return document.querySelectorAll(".col-md-4 .card")[1];
        },
        position: "left"
      }
    ];
  }

  init() {
    // Проверяем, показывали ли мы уже гид
    const guideViewed = localStorage.getItem('studyGuideViewed') === 'true';

    if (!guideViewed) {
      this.showGuide();
    } else {
      this.createHelpButton();
    }
  }

  createHelpButton() {
    const helpButton = document.createElement('div');
    helpButton.className = 'help-button';
    helpButton.innerHTML = `
      <button class="btn btn-primary rounded-circle" title="Показать подсказки">
        <i class="fas fa-question"></i>
      </button>
    `;
    document.body.appendChild(helpButton);

    helpButton.querySelector('button').addEventListener('click', () => {
      this.showGuide();
    });

    this.helpButton = helpButton;
  }

  showGuide() {
    // Удаляем кнопку помощи, если она есть
    if (this.helpButton) {
      this.helpButton.remove();
      this.helpButton = null;
    }

    // Создаем полупрозрачную подложку
    this.overlayElement = document.createElement('div');
    this.overlayElement.className = 'study-guide-overlay';
    document.body.appendChild(this.overlayElement);

    // Создаем блок с подсказкой
    this.tooltipElement = document.createElement('div');
    this.tooltipElement.className = 'study-guide-tooltip';

    // Добавляем возможность перетаскивания
    this.tooltipElement.addEventListener('mousedown', this.startDragTooltip.bind(this));
    document.addEventListener('mousemove', this.dragTooltip.bind(this));
    document.addEventListener('mouseup', this.stopDragTooltip.bind(this));

    document.body.appendChild(this.tooltipElement);

    // Создаем индикатор прогресса
    this.progressDotsElement = document.createElement('div');
    this.progressDotsElement.className = 'progress-dots';
    document.body.appendChild(this.progressDotsElement);

    // Генерируем точки прогресса
    this.updateProgressDots();

    // Показываем первую подсказку
    this.showTip(0);

    // Добавляем обработчики прокрутки и изменения размера
    window.addEventListener('scroll', this.positionTooltip.bind(this));
    window.addEventListener('resize', this.positionTooltip.bind(this));
  }

  // Методы для перетаскивания подсказки
  startDragTooltip(e) {
    // Проверяем, что клик был не на кнопке
    if (e.target.tagName === 'BUTTON') return;

    this.isTooltipDragging = true;
    const rect = this.tooltipElement.getBoundingClientRect();
    this.tooltipDragStartX = e.clientX - rect.left;
    this.tooltipDragStartY = e.clientY - rect.top;

    // Добавляем класс, показывающий, что подсказка перетаскивается
    this.tooltipElement.classList.add('dragging');
  }

  dragTooltip(e) {
    if (!this.isTooltipDragging) return;

    const left = e.clientX - this.tooltipDragStartX;
    const top = e.clientY - this.tooltipDragStartY;

    this.tooltipElement.style.left = `${left}px`;
    this.tooltipElement.style.top = `${top}px`;
  }

  stopDragTooltip() {
    this.isTooltipDragging = false;
    if (this.tooltipElement) {
      this.tooltipElement.classList.remove('dragging');
    }
  }

  updateProgressDots() {
    this.progressDotsElement.innerHTML = '';

    for (let i = 0; i < this.tips.length; i++) {
      const dot = document.createElement('div');
      dot.className = i === this.currentTipIndex ? 'dot active' : 'dot';
      this.progressDotsElement.appendChild(dot);
    }
  }

  showTip(index) {
    // Очищаем предыдущую подсветку
    if (this.targetElementHighlight) {
      this.targetElementHighlight.classList.remove('highlight-element');
    }

    this.currentTipIndex = index;
    const tip = this.tips[index];

    // Находим целевой элемент используя функцию поиска
    const targetElement = tip.targetFinder();

    if (targetElement) {
      targetElement.classList.add('highlight-element');
      this.targetElementHighlight = targetElement;

      // Прокручиваем к элементу, если он не виден
      const rect = targetElement.getBoundingClientRect();
      if (
        rect.top < 50 ||
        rect.bottom > window.innerHeight - 50 ||
        rect.left < 0 ||
        rect.right > window.innerWidth
      ) {
        // Используем плавную прокрутку с небольшим отступом
        window.scrollTo({
          top: window.scrollY + rect.top - 100,
          behavior: 'smooth'
        });
      }
    }

    // Обновляем содержимое подсказки
    this.tooltipElement.innerHTML = `
      <div class="tooltip-header">
        <div class="step-indicator">${index + 1}/${this.tips.length}</div>
        <h4>${tip.title}</h4>
      </div>
      <p>${tip.description}</p>
      <div class="move-hint">Подсказку можно перетаскивать, если она мешает</div>
      <div class="tooltip-buttons">
        <div>
          <button class="btn btn-sm btn-outline-secondary me-2 prev-button" ${index === 0 ? 'disabled' : ''}>
            ← Назад
          </button>
        </div>
        <div>
          <button class="btn btn-sm btn-outline-secondary me-2 skip-button">
            Пропустить
          </button>
          <button class="btn btn-sm btn-primary next-button">
            ${index < this.tips.length - 1 ? 'Далее →' : 'Готово'}
          </button>
        </div>
      </div>
    `;

    // Добавляем обработчики кнопок
    this.tooltipElement.querySelector('.prev-button').addEventListener('click', () => {
      if (index > 0) {
        this.showTip(index - 1);
      }
    });

    this.tooltipElement.querySelector('.next-button').addEventListener('click', () => {
      if (index < this.tips.length - 1) {
        this.showTip(index + 1);
      } else {
        this.endGuide();
      }
    });

    this.tooltipElement.querySelector('.skip-button').addEventListener('click', () => {
      this.endGuide();
    });

    // Позиционируем подсказку
    this.positionTooltip();

    // Обновляем индикатор прогресса
    this.updateProgressDots();
  }

  positionTooltip() {
    // Если подсказка перетаскивается, не меняем ее положение
    if (this.isTooltipDragging) return;

    const tip = this.tips[this.currentTipIndex];
    const targetElement = tip.targetFinder();

    if (!targetElement || !this.tooltipElement) return;

    const targetRect = targetElement.getBoundingClientRect();
    const tooltipRect = this.tooltipElement.getBoundingClientRect();

    const position = tip.position;
    let left, top;

    switch (position) {
      case 'top':
        left = targetRect.left + targetRect.width/2 - tooltipRect.width/2;
        top = targetRect.top - tooltipRect.height - 10;
        break;
      case 'bottom':
        left = targetRect.left + targetRect.width/2 - tooltipRect.width/2;
        top = targetRect.bottom + 10;
        break;
      case 'left':
        left = targetRect.left - tooltipRect.width - 10;
        top = targetRect.top + targetRect.height/2 - tooltipRect.height/2;
        break;
      case 'right':
        left = targetRect.right + 10;
        top = targetRect.top + targetRect.height/2 - tooltipRect.height/2;
        break;
      case 'top-right':
        left = targetRect.right - tooltipRect.width/4;
        top = targetRect.top - tooltipRect.height - 10;
        break;
      case 'top-left':
        left = targetRect.left - tooltipRect.width*3/4;
        top = targetRect.top - tooltipRect.height - 10;
        break;
      case 'bottom-right':
        left = targetRect.right - tooltipRect.width/4;
        top = targetRect.bottom + 10;
        break;
      case 'bottom-left':
        left = targetRect.left - tooltipRect.width*3/4;
        top = targetRect.bottom + 10;
        break;
      case 'middle':
      default:
        // Размещаем в правом верхнем углу экрана, чтобы не мешать
        left = window.innerWidth - tooltipRect.width - 20;
        top = 20;
    }

    // Проверка, чтобы подсказка не выходила за границы экрана
    if (left < 10) left = 10;
    if (left + tooltipRect.width > window.innerWidth - 10)
      left = window.innerWidth - tooltipRect.width - 10;
    if (top < 10) top = 10;
    if (top + tooltipRect.height > window.innerHeight - 10)
      top = window.innerHeight - tooltipRect.height - 10;

    this.tooltipElement.style.left = `${left}px`;
    this.tooltipElement.style.top = `${top}px`;
  }

  endGuide() {
    // Очищаем подсветку
    if (this.targetElementHighlight) {
      this.targetElementHighlight.classList.remove('highlight-element');
    }

    // Удаляем обработчики перетаскивания
    document.removeEventListener('mousemove', this.dragTooltip.bind(this));
    document.removeEventListener('mouseup', this.stopDragTooltip.bind(this));

    // Удаляем элементы гида
    if (this.overlayElement) {
      this.overlayElement.remove();
    }
    if (this.tooltipElement) {
      this.tooltipElement.remove();
    }
    if (this.progressDotsElement) {
      this.progressDotsElement.remove();
    }

    // Удаляем обработчики событий
    window.removeEventListener('scroll', this.positionTooltip.bind(this));
    window.removeEventListener('resize', this.positionTooltip.bind(this));

    // Сохраняем в localStorage, что гид был просмотрен
    localStorage.setItem('studyGuideViewed', 'true');

    // Показываем кнопку помощи
    this.createHelpButton();
  }
}

// Инициализируем гид после загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
  const guide = new StudyGuide();

  // Отложенный запуск гида, чтобы страница успела загрузиться
  setTimeout(() => {
    guide.init();
  }, 1000);

  // Добавляем глобальную функцию для возможности вызова из HTML
  window.showStudyGuide = function() {
    guide.showGuide();
  };
});