document.addEventListener('DOMContentLoaded', function() {
    // Основные элементы интерфейса
    const bookContent = document.getElementById('book-content');
    const bookId = bookContent.getAttribute('data-book-id');
    const progressBar = document.getElementById('reading-progress');
    const progressBarTop = document.getElementById('reading-progress-top');
    const progressPercent = document.getElementById('progress-percent');
    const saveButton = document.getElementById('save-position');
    const statusMessage = document.getElementById('status-message');
    const fontSizeValue = document.getElementById('font-size-value');
    const increaseFontBtn = document.getElementById('increase-font');
    const decreaseFontBtn = document.getElementById('decrease-font');
    const toggleDarkModeBtn = document.getElementById('toggle-dark-mode');
    const toggleFullscreenBtn = document.getElementById('toggle-fullscreen');
    const fontSerifBtn = document.getElementById('font-serif');
    const fontSansBtn = document.getElementById('font-sans');
    const addBookmarkBtn = document.getElementById('add-bookmark');
    const bookmarksContainer = document.getElementById('bookmarks-container');
    const noBookmarksMsg = document.getElementById('no-bookmarks');
    const contentsBtn = document.getElementById('contents-btn');
    const bookHeader = document.querySelector('.book-header');
    const bookTitle = document.querySelector('.book-title').textContent;
    const readingContainer = document.querySelector('.reading-container');

    // Настройки
    let currentFontSize = parseInt(fontSizeValue.textContent) || 18;
    let isDarkMode = false;
    let bookmarks = JSON.parse(localStorage.getItem(`book_bookmarks_${bookId}`) || '[]');

    // Делаем контейнер книги скроллируемым с фиксированной высотой
    function setupScrollableContainer() {
        // Добавляем класс для скроллируемого контейнера
        bookContent.classList.add('scroll-container');

        // Перемещаем обложку книги в начало контента
        moveBookCoverToContent();

        // Восстанавливаем позицию скролла из localStorage
        const savedScrollPosition = localStorage.getItem(`book_scroll_position_${bookId}`);
        if (savedScrollPosition) {
            bookContent.scrollTop = parseInt(savedScrollPosition);
        }

        // Обработчик скролла для сохранения позиции
        bookContent.addEventListener('scroll', function() {
            // Обновляем прогресс
            updateProgressBar();

            // Сохраняем позицию с задержкой для производительности
            clearTimeout(window.scrollSaveTimeout);
            window.scrollSaveTimeout = setTimeout(function() {
                const scrollPosition = bookContent.scrollTop;
                localStorage.setItem(`book_scroll_position_${bookId}`, scrollPosition);
            }, 500);
        });
    }

    // Перемещаем обложку книги в начало контента
    function moveBookCoverToContent() {
        // Проверяем, не добавлена ли уже обложка в контент
        if (bookContent.querySelector('.content-book-header')) {
            return; // Обложка уже добавлена, выходим
        }

        // Находим обложку книги
        const coverContainer = document.querySelector('.book-cover-container');

        // Если обложка существует
        if (coverContainer) {
            // Создаем новый контейнер для обложки внутри контента
            const contentCover = document.createElement('div');
            contentCover.className = 'content-book-header';

            // Получаем путь к изображению обложки
            const coverImage = coverContainer.querySelector('img');
            const coverSrc = coverImage ? coverImage.src : '';
            const coverAlt = coverImage ? coverImage.alt : 'Book cover';

            // Создаем HTML для заголовка и обложки
            contentCover.innerHTML = `
                <div class="content-book-info">
                    <h1 class="content-book-title">${bookTitle}</h1>
                    <div class="content-book-cover">
                        <img src="${coverSrc}" alt="${coverAlt}" class="content-cover-image">
                    </div>
                </div>
            `;

            // Вставляем новую обложку в начало контента
            bookContent.insertBefore(contentCover, bookContent.firstChild);
        }

        // Скрываем оригинальную обложку в шапке (она уже скрыта в HTML)
        const bookHeader = document.querySelector('.book-header');
        if (bookHeader) {
            bookHeader.style.display = 'none';
        }
    }

    // Сохранение текущей позиции скролла
    function saveScrollPosition() {
        const scrollPosition = bookContent.scrollTop;
        localStorage.setItem(`book_scroll_position_${bookId}`, scrollPosition);
        showStatusMessage('Position saved', 'success');
    }

    // Восстановление сохраненной позиции скролла
    function restoreScrollPosition() {
        const savedPosition = localStorage.getItem(`book_scroll_position_${bookId}`);
        if (savedPosition) {
            bookContent.scrollTop = parseInt(savedPosition);
            showStatusMessage('Returned to saved position', 'success');
        } else {
            showStatusMessage('No saved position found', 'error');
        }
    }

    // Обновление индикатора прогресса
    function updateProgressBar() {
        const scrollPosition = bookContent.scrollTop;
        const scrollHeight = bookContent.scrollHeight - bookContent.clientHeight;

        if (scrollHeight <= 0) return; // Предотвращаем деление на ноль

        const percentage = Math.min(100, (scrollPosition / scrollHeight) * 100);

        // Обновляем индикаторы прогресса
        progressBar.style.width = percentage + '%';
        progressBarTop.style.width = percentage + '%';
        progressPercent.textContent = Math.round(percentage) + '%';
    }

    // Обрабатываем контент - оборачиваем слова в интерактивные элементы
    function processBookContent() {
        // Получаем все параграфы и заголовки
        const textElements = bookContent.querySelectorAll('p, h1, h2, h3, h4, h5, h6');

        textElements.forEach(element => {
            // Проверяем, не обработан ли элемент уже
            if (element.getAttribute('data-processed')) return;

            // Получаем текст элемента
            const text = element.innerHTML;

            // Заменяем только английские слова длиной 2+ символов,
            // исключая слова внутри уже существующих HTML-тегов
            let processedText = text.replace(/(\b[a-zA-Z]{2,}\b)(?![^<]*>|[^<>]*<\/)/g, '<span class="word">$1</span>');

            // Обновляем HTML параграфа и помечаем как обработанный
            element.innerHTML = processedText;
            element.setAttribute('data-processed', 'true');
        });

        // Добавляем обработчики событий для всех слов
        const words = document.querySelectorAll('.word:not([data-has-events])');
        words.forEach(word => {
            word.addEventListener('mouseenter', showTranslation);
            word.addEventListener('mouseleave', hideTranslation);
            word.setAttribute('data-has-events', 'true');
        });
    }

    // Показываем перевод при наведении на слово
    function showTranslation(event) {
        const word = event.target;
        const wordText = word.textContent.toLowerCase();

        console.log('Showing translation for word:', wordText);

        // Удаляем существующие подсказки, если есть
        document.querySelectorAll('.word-tooltip').forEach(t => t.remove());

        // Создаем подсказку
        const tooltip = document.createElement('div');
        tooltip.className = 'word-tooltip';
        tooltip.textContent = 'Loading...';
        word.appendChild(tooltip);

        // Устанавливаем позицию
        positionTooltip(tooltip, word);

        // Запрашиваем перевод
        console.log(`Fetching translation from: /books/api/word-translation/${wordText}`);
        fetch(`/books/api/word-translation/${wordText}`)
            .then(response => {
                console.log('Translation response status:', response.status);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log('Translation data received:', data);
                if (data.translation) {
                    // Создаем контейнер для заголовка с аудио
                    const headerContainer = document.createElement('div');
                    headerContainer.className = 'tooltip-header';
                    headerContainer.style.display = 'flex';
                    headerContainer.style.alignItems = 'center';
                    headerContainer.style.justifyContent = 'space-between';
                    headerContainer.style.marginBottom = '5px';

                    // Создаем индикатор статуса
                    const statusDot = document.createElement('span');
                    statusDot.className = `word-status status-${data.status || 0}`;

                    // Создаем кнопку аудио, если доступно
                    let audioButton = null;
                    if (data.has_audio && data.audio_url) {
                        audioButton = document.createElement('button');
                        audioButton.className = 'tooltip-audio-btn';
                        audioButton.innerHTML = '<i class="fas fa-volume-up"></i>';
                        audioButton.title = 'Произношение';
                        audioButton.style.cssText = `
                            background: #4e73df;
                            color: white;
                            border: none;
                            border-radius: 3px;
                            padding: 4px 8px;
                            cursor: pointer;
                            font-size: 12px;
                            margin-left: 5px;
                        `;
                        
                        // Обработчик клика для воспроизведения аудио
                        audioButton.addEventListener('click', function(e) {
                            e.preventDefault();
                            e.stopPropagation();
                            playWordAudio(data.audio_url);
                        });

                        // Автоматическое воспроизведение через 1 секунду (опционально)
                        // Можно закомментировать, если не нужно
                        setTimeout(() => {
                            playWordAudio(data.audio_url);
                        }, 1000);
                    }

                    // Обновляем содержимое
                    tooltip.innerHTML = '';
                    
                    // Добавляем заголовок с статусом и аудио
                    headerContainer.appendChild(statusDot);
                    if (audioButton) {
                        headerContainer.appendChild(audioButton);
                    }
                    tooltip.appendChild(headerContainer);

                    // Если это форма другого слова (например, прошедшее время)
                    if (data.is_form && data.form_text && data.base_form) {
                        const formInfo = document.createElement('div');
                        formInfo.className = 'word-form-info';
                        formInfo.innerHTML = `<em>${data.form_text} "${data.base_form}"</em>`;
                        tooltip.appendChild(formInfo);
                    }

                    // Добавляем основной перевод
                    const translationText = document.createElement('div');
                    translationText.className = 'translation-text';
                    translationText.textContent = data.translation;
                    tooltip.appendChild(translationText);

                    // Если есть варианты перевода (формы слова от pymorphy2)
                    if (data.translation_variants && data.translation_variants.length > 0) {
                        const variantsContainer = document.createElement('div');
                        variantsContainer.className = 'translation-variants';

                        data.translation_variants.forEach(variant => {
                            const variantElement = document.createElement('div');
                            variantElement.className = 'translation-variant';
                            variantElement.textContent = variant;
                            variantsContainer.appendChild(variantElement);
                        });

                        tooltip.appendChild(variantsContainer);
                    }

                    // Добавляем кнопку "Learn" если слово не в колоде "Слова из чтения"
                    if (!data.in_reading_deck) {
                        const addButton = document.createElement('span');
                        addButton.className = 'add-to-learning';
                        addButton.innerHTML = '<i class="fas fa-plus"></i> Learn';
                        addButton.dataset.wordId = data.id;

                        addButton.addEventListener('click', function(e) {
                            e.stopPropagation();
                            addToLearning(data.id, wordText, this);
                        });

                        tooltip.appendChild(addButton);
                    }
                } else {
                    tooltip.textContent = 'Translation not available';
                }

                // Обновляем позицию с учетом нового содержимого
                positionTooltip(tooltip, word);
            })
            .catch(error => {
                console.error('Error fetching translation:', error);
                tooltip.textContent = `Error: ${error.message}`;
                tooltip.style.backgroundColor = '#ff6b6b';
                tooltip.style.color = 'white';
            });
    }

    // Позиционируем подсказку
    function positionTooltip(tooltip, word) {
        const wordRect = word.getBoundingClientRect();
        const containerRect = bookContent.getBoundingClientRect();

        tooltip.style.position = 'absolute';
        tooltip.style.display = 'block';
        tooltip.style.bottom = '100%';
        tooltip.style.left = '50%';
        tooltip.style.transform = 'translateX(-50%)';
        tooltip.style.marginBottom = '5px';
        tooltip.style.zIndex = '1000';

        // После отрисовки проверяем позицию и корректируем при необходимости
        setTimeout(() => {
            const tooltipRect = tooltip.getBoundingClientRect();

            // Проверка на выход за верхний край контейнера
            if (tooltipRect.top < containerRect.top) {
                tooltip.style.bottom = 'auto';
                tooltip.style.top = '100%';
                tooltip.style.marginBottom = '0';
                tooltip.style.marginTop = '5px';
            }

            // Проверка на выход за левый край
            if (tooltipRect.left < containerRect.left) {
                tooltip.style.left = '0';
                tooltip.style.transform = 'translateX(0)';
            }

            // Проверка на выход за правый край
            if (tooltipRect.right > containerRect.right) {
                tooltip.style.left = 'auto';
                tooltip.style.right = '0';
                tooltip.style.transform = 'translateX(0)';
            }
        }, 0);
    }

    // Скрываем перевод при уходе с слова
    function hideTranslation(event) {
        const tooltip = event.target.querySelector('.word-tooltip');
        if (tooltip) {
            tooltip.remove();
        }
    }

    // Функция для воспроизведения аудио слова
    function playWordAudio(audioUrl) {
        console.log('Playing audio:', audioUrl);
        
        // Используем существующий audio элемент или создаем новый
        let audio = document.getElementById('wordAudio');
        if (!audio) {
            audio = document.createElement('audio');
            audio.id = 'wordAudio';
            audio.style.display = 'none';
            document.body.appendChild(audio);
        }

        // Останавливаем текущее воспроизведение, если есть
        audio.pause();
        audio.currentTime = 0;

        // Устанавливаем новый источник и воспроизводим
        audio.src = audioUrl;
        audio.play().catch(error => {
            console.error('Ошибка воспроизведения аудио:', error);
        });
    }


    // Простая подсказка для полноэкранного режима
    function showSimpleMobileHint() {
        // Проверяем, показывали ли уже подсказку
        const hasSeenHint = localStorage.getItem('simple_mobile_reader_hint_shown');
        if (hasSeenHint) return;

        const hint = document.createElement('div');
        hint.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 20px;
            border-radius: 10px;
            z-index: 10002;
            max-width: 250px;
            text-align: center;
            font-size: 16px;
        `;

        hint.innerHTML = `
            <div style="margin-bottom: 15px;">
                <strong>Режим чтения</strong><br>
                Тапните на слово для перевода<br>
                Кнопка ✕ для выхода
            </div>
            <button onclick="this.parentNode.remove(); localStorage.setItem('simple_mobile_reader_hint_shown', 'true')" style="
                background: #4e73df;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
                cursor: pointer;
            ">ОК</button>
        `;

        document.body.appendChild(hint);

        // Автозакрытие через 4 секунды
        setTimeout(() => {
            if (hint.parentNode) {
                hint.remove();
                localStorage.setItem('simple_mobile_reader_hint_shown', 'true');
            }
        }, 4000);
    }

    // Добавление слова в очередь изучения
    function addToLearning(wordId, wordText, buttonElement) {
        fetch('/api/add-to-learning', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ word_id: wordId }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showStatusMessage(data.message || 'Word added to learning queue', 'success');

                // Обновляем индикатор статуса
                if (data.new_status) {
                    const tooltipElement = buttonElement.parentNode;
                    const statusDot = tooltipElement.querySelector('.word-status');
                    if (statusDot) {
                        statusDot.className = `word-status status-${data.new_status}`;
                    }

                    // Удаляем кнопку, так как слово уже в очереди
                    buttonElement.remove();
                }
            } else {
                showStatusMessage(data.error || 'Error adding word', 'error');
            }
        })
        .catch(error => {
            showStatusMessage('Error adding word to learning queue', 'error');
        });
    }

    // Отображение статусного сообщения
    function showStatusMessage(message, type) {
        statusMessage.textContent = message;
        statusMessage.className = 'ms-3 text-' + (type === 'error' ? 'danger' : 'success');

        // Удаление сообщения через 3 секунды
        setTimeout(() => {
            statusMessage.textContent = '';
        }, 3000);
    }

    // Сохранение настроек чтения
    function saveReadingSettings() {
        const settings = {
            fontSize: currentFontSize,
            fontFamily: bookContent.style.fontFamily || 'Georgia, serif',
            darkMode: isDarkMode
        };
        localStorage.setItem(`book_settings_${bookId}`, JSON.stringify(settings));
    }

    // Восстановление настроек чтения
    function restoreReadingSettings() {
        const savedSettings = localStorage.getItem(`book_settings_${bookId}`);
        if (savedSettings) {
            try {
                const settings = JSON.parse(savedSettings);

                // Восстанавливаем размер шрифта
                if (settings.fontSize) {
                    currentFontSize = settings.fontSize;
                    bookContent.style.fontSize = currentFontSize + 'px';
                    fontSizeValue.textContent = currentFontSize + 'px';
                }

                // Восстанавливаем шрифт
                if (settings.fontFamily) {
                    bookContent.style.fontFamily = settings.fontFamily;
                    if (settings.fontFamily.includes('Nunito')) {
                        fontSansBtn.classList.add('active');
                        fontSerifBtn.classList.remove('active');
                    } else {
                        fontSerifBtn.classList.add('active');
                        fontSansBtn.classList.remove('active');
                    }
                }

                // Восстанавливаем тему
                if (settings.darkMode) {
                    isDarkMode = settings.darkMode;
                    if (isDarkMode) {
                        bookContent.classList.add('dark-mode');
                        toggleDarkModeBtn.innerHTML = '<i class="fas fa-sun"></i>';
                    }
                }
            } catch (e) {
                console.error("Error restoring reading settings:", e);
            }
        }
    }

    // Функция для переключения полноэкранного режима с поддержкой мобильных устройств
    function toggleFullscreen(element) {
        // Определяем, используется ли мобильное устройство
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

        // Проверяем, активен ли полноэкранный режим
        if (!document.fullscreenElement &&    // Стандартное свойство
            !document.mozFullScreenElement && // Firefox
            !document.webkitFullscreenElement && // Chrome, Safari и Opera
            !document.msFullscreenElement) {  // IE/Edge

            // Для мобильных устройств используем альтернативный подход "псевдо-полноэкранного режима"
            if (isMobile) {
                // Добавляем класс для мобильного псевдо-полноэкранного режима
                document.body.classList.add('mobile-fullscreen-mode');
                if (isDarkMode) {
                    document.body.classList.add('dark-mode');
                }
                element.classList.add('mobile-fullscreen');

                // Скрываем ненужные элементы при чтении
                document.querySelectorAll('header, footer, .breadcrumb, .btn-outline-primary').forEach(el => {
                    if (el) el.style.display = 'none';
                });
                
                addExitFullscreenButton();
                
                // Обновляем кнопку
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
                toggleFullscreenBtn.title = 'Exit fullscreen';

                // Показываем подсказку пользователю (только первый раз)
                showSimpleMobileHint();

                return; // Выходим из функции, чтобы не выполнять стандартный fullscreen API
            }

            // Запрашиваем полноэкранный режим для десктопа
            try {
                if (element.requestFullscreen) {
                    element.requestFullscreen();
                } else if (element.mozRequestFullScreen) { // Firefox
                    element.mozRequestFullScreen();
                } else if (element.webkitRequestFullscreen) { // Chrome, Safari и Opera
                    element.webkitRequestFullscreen();
                } else if (element.msRequestFullscreen) { // IE/Edge
                    element.msRequestFullscreen();
                }

                // Меняем иконку на "свернуть"
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
                toggleFullscreenBtn.title = 'Exit fullscreen';
            } catch (error) {
                console.error('Fullscreen API error:', error);
                // При ошибке, пробуем использовать мобильный режим как запасной вариант
                document.body.classList.add('mobile-fullscreen-mode');
                if (isDarkMode) {
                    document.body.classList.add('dark-mode');
                }
                element.classList.add('mobile-fullscreen');
                addExitFullscreenButton();
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
                
                // Показываем подсказку пользователю (только первый раз)
                showSimpleMobileHint();
            }

        } else {
            // Выход из полноэкранного режима

            // Проверяем, активен ли мобильный псевдо-полноэкранный режим
            if (document.body.classList.contains('mobile-fullscreen-mode')) {
                // Выход из мобильного псевдо-полноэкранного режима
                document.body.classList.remove('mobile-fullscreen-mode');
                document.body.classList.remove('dark-mode');
                element.classList.remove('mobile-fullscreen');

                const exitBtn = document.getElementById('mobile-exit-fullscreen');
                if (exitBtn) {
                    exitBtn.remove();
                }

                // Восстанавливаем видимость скрытых элементов
                document.querySelectorAll('header, footer, .breadcrumb, .btn-outline-primary').forEach(el => {
                    if (el) el.style.display = '';
                });

                // Меняем иконку обратно на "расширить"
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
                toggleFullscreenBtn.title = 'Enter fullscreen';

                return; // Выходим из функции
            }

            // Выход из стандартного полноэкранного режима
            try {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.mozCancelFullScreen) { // Firefox
                    document.mozCancelFullScreen();
                } else if (document.webkitExitFullscreen) { // Chrome, Safari и Opera
                    document.webkitExitFullscreen();
                } else if (document.msExitFullscreen) { // IE/Edge
                    document.msExitFullscreen();
                }

                // Меняем иконку обратно на "расширить"
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
                toggleFullscreenBtn.title = 'Enter fullscreen';
            } catch (error) {
                console.error('Exiting fullscreen error:', error);
                // Сброс состояния
                toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
            }
        }
    }

    function addExitFullscreenButton() {
        // Проверяем, существует ли уже кнопка
        if (document.getElementById('mobile-exit-fullscreen')) {
            return;
        }

        // Создаем кнопку выхода
        const exitButton = document.createElement('button');
        exitButton.id = 'mobile-exit-fullscreen';
        exitButton.className = 'mobile-exit-btn';
        exitButton.innerHTML = '<i class="fas fa-times"></i>';
        exitButton.title = 'Exit fullscreen';

        // Добавляем обработчик события
        exitButton.addEventListener('click', function() {
            // Выход из мобильного псевдо-полноэкранного режима
            document.body.classList.remove('mobile-fullscreen-mode');
            document.body.classList.remove('dark-mode');
            readingContainer.classList.remove('mobile-fullscreen');

            // Восстанавливаем видимость скрытых элементов
            document.querySelectorAll('header, footer, .breadcrumb, .btn-outline-primary').forEach(el => {
                if (el) el.style.display = '';
            });

            // Обновляем кнопку полноэкранного режима
            toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
            toggleFullscreenBtn.title = 'Enter fullscreen';

            // Удаляем кнопку выхода
            this.remove();
        });

        // Добавляем кнопку в контейнер для чтения
        readingContainer.appendChild(exitButton);
    }

    // Обновление состояния кнопки полноэкранного режима
    function updateFullscreenButtonState() {
        // Проверяем стандартный полноэкранный режим
        const isStandardFullscreen = document.fullscreenElement ||
                                   document.webkitFullscreenElement ||
                                   document.mozFullScreenElement ||
                                   document.msFullscreenElement;

        // Проверяем мобильный псевдо-полноэкранный режим
        const isMobileFullscreen = document.body.classList.contains('mobile-fullscreen-mode');

        if (!isStandardFullscreen && !isMobileFullscreen) {
            // Если оба режима неактивны, показываем иконку "развернуть"
            toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
            toggleFullscreenBtn.title = 'Enter fullscreen';
        } else {
            // Если активен любой из режимов, показываем иконку "свернуть"
            toggleFullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
            toggleFullscreenBtn.title = 'Exit fullscreen';
        }
    }

    // Получение контекста в текущей позиции
    function getContextAtCurrentPosition() {
        // В скроллируемом контейнере находим элемент, который виден в верхней части видимой области
        const viewportTop = bookContent.scrollTop;
        const elements = bookContent.querySelectorAll('p, h1, h2, h3, h4, h5, h6');

        // Ищем первый видимый элемент
        let contextElement = null;
        for (let el of elements) {
            if (el.offsetTop >= viewportTop) {
                contextElement = el;
                break;
            }
        }

        // Если не нашли, берем первый элемент
        if (!contextElement && elements.length > 0) {
            contextElement = elements[0];
        }

        // Если нашли элемент, получаем текст
        if (contextElement) {
            let context = contextElement.textContent.trim();
            // Ограничиваем длину
            if (context.length > 100) {
                context = context.substring(0, 100) + '...';
            }
            return context;
        }

        return 'Current position';
    }

    // Обновление списка закладок
    function updateBookmarksList() {
        // Очищаем существующий список
        while (bookmarksContainer.firstChild) {
            bookmarksContainer.removeChild(bookmarksContainer.firstChild);
        }

        // Показываем сообщение, если нет закладок
        if (bookmarks.length === 0) {
            bookmarksContainer.appendChild(noBookmarksMsg);
            return;
        }

        // Добавляем закладки в список
        bookmarks.forEach((bookmark, index) => {
            const bookmarkItem = document.createElement('li');
            bookmarkItem.className = 'dropdown-item d-flex justify-content-between align-items-center';
            bookmarkItem.innerHTML = `
                <span class="bookmark-text" title="${bookmark.context}">${bookmark.name}</span>
                <button class="btn btn-sm btn-link text-danger remove-bookmark p-0 ms-2" data-index="${index}">
                    <i class="fas fa-times"></i>
                </button>
            `;

            // Обработчик клика по закладке
            bookmarkItem.addEventListener('click', function(e) {
                if (!e.target.closest('.remove-bookmark')) {
                    // Прокручиваем к позиции закладки
                    bookContent.scrollTop = bookmark.position;
                }
            });

            bookmarksContainer.appendChild(bookmarkItem);
        });

        // Обработчики для удаления закладок
        document.querySelectorAll('.remove-bookmark').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const index = parseInt(this.dataset.index);
                bookmarks.splice(index, 1);
                localStorage.setItem(`book_bookmarks_${bookId}`, JSON.stringify(bookmarks));
                updateBookmarksList();
            });
        });
    }

    // Создание оглавления
    function createTableOfContents() {
        // Получаем все заголовки
        const headings = bookContent.querySelectorAll('h1, h2, h3, h4, h5, h6');

        // Если заголовков нет, создаем их на основе деления текста на части
        if (headings.length === 0) {
            createChapterHeadings();
        }

        // Формируем HTML для оглавления
        const tocHTML = document.createElement('div');
        tocHTML.className = 'table-of-contents';

        const tocList = document.createElement('ul');
        tocList.className = 'toc-list list-unstyled';

        // Получаем обновленный список заголовков
        const updatedHeadings = bookContent.querySelectorAll('h1, h2, h3, h4, h5, h6');

        updatedHeadings.forEach((heading, index) => {
            // Не добавляем в оглавление заголовок книги
            if (heading.closest('.content-book-header')) return;

            // Создаем ID для заголовка, если его нет
            if (!heading.id) {
                heading.id = `heading-${index}`;
            }

            // Создаем элемент списка
            const listItem = document.createElement('li');
            listItem.className = `toc-item toc-level-${heading.tagName.toLowerCase()}`;

            const link = document.createElement('a');
            link.href = `#${heading.id}`;
            link.textContent = heading.textContent;
            link.className = 'toc-link';

            // Обработчик клика по ссылке
            link.addEventListener('click', function(e) {
                e.preventDefault();

                // Закрываем модальное окно с оглавлением
                const tocModal = bootstrap.Modal.getInstance(document.getElementById('contentsModal'));
                if (tocModal) {
                    tocModal.hide();
                }

                // Задержка для завершения анимации закрытия модального окна
                setTimeout(() => {
                    // Прокрутка к заголовку
                    const targetHeading = document.getElementById(heading.id);
                    if (targetHeading) {
                        // Прокручиваем контейнер, чтобы заголовок был виден
                        bookContent.scrollTo({
                            top: targetHeading.offsetTop - 20,
                            behavior: 'smooth'
                        });

                        // Сохраняем позицию
                        localStorage.setItem(`book_scroll_position_${bookId}`, targetHeading.offsetTop - 20);

                        // Обновляем индикатор прогресса
                        setTimeout(updateProgressBar, 100);
                    }
                }, 300);
            });

            listItem.appendChild(link);
            tocList.appendChild(listItem);
        });

        tocHTML.appendChild(tocList);

        // Вставляем оглавление в модальное окно
        const tocContainer = document.getElementById('contents-container');
        if (tocContainer) {
            tocContainer.innerHTML = '';
            tocContainer.appendChild(tocHTML);
        }
    }

    // Создание заголовков глав для книги без структуры
    function createChapterHeadings() {
        // Получаем все параграфы
        const paragraphs = bookContent.querySelectorAll('p');
        if (paragraphs.length === 0) return;

        // Определяем количество глав в зависимости от размера книги
        const totalParagraphs = paragraphs.length;
        const chaptersCount = Math.min(10, Math.max(3, Math.ceil(totalParagraphs / 20)));

        // Создаем заголовки равномерно по тексту
        for (let i = 0; i < chaptersCount; i++) {
            const position = Math.floor(i * totalParagraphs / chaptersCount);
            if (position < paragraphs.length) {
                const paragraph = paragraphs[position];

                // Создаем заголовок
                const heading = document.createElement('h2');
                heading.id = `chapter-${i + 1}`;
                heading.textContent = `Chapter ${i + 1}`;
                heading.className = 'generated-chapter';

                // Вставляем перед параграфом
                paragraph.parentNode.insertBefore(heading, paragraph);
            }
        }
    }

    // Обработчики событий

    // Обработчики для изменения размера шрифта
    increaseFontBtn.addEventListener('click', function() {
        if (currentFontSize < 32) {
            currentFontSize += 2;
            bookContent.style.fontSize = currentFontSize + 'px';
            fontSizeValue.textContent = currentFontSize + 'px';
            saveReadingSettings();
        }
    });

    decreaseFontBtn.addEventListener('click', function() {
        if (currentFontSize > 12) {
            currentFontSize -= 2;
            bookContent.style.fontSize = currentFontSize + 'px';
            fontSizeValue.textContent = currentFontSize + 'px';
            saveReadingSettings();
        }
    });

    // Обработчики для выбора шрифта
    fontSerifBtn.addEventListener('click', function() {
        bookContent.style.fontFamily = 'Georgia, serif';
        fontSerifBtn.classList.add('active');
        fontSansBtn.classList.remove('active');
        saveReadingSettings();
    });

    fontSansBtn.addEventListener('click', function() {
        bookContent.style.fontFamily = 'Nunito, sans-serif';
        fontSansBtn.classList.add('active');
        fontSerifBtn.classList.remove('active');
        saveReadingSettings();
    });

    // Переключение темной темы
    toggleDarkModeBtn.addEventListener('click', function() {
        isDarkMode = !isDarkMode;

        if (isDarkMode) {
            bookContent.classList.add('dark-mode');
            if (document.body.classList.contains('mobile-fullscreen-mode')) {
                document.body.classList.add('dark-mode');
            }
            this.innerHTML = '<i class="fas fa-sun"></i>';
        } else {
            bookContent.classList.remove('dark-mode');
            document.body.classList.remove('dark-mode');
            this.innerHTML = '<i class="fas fa-moon"></i>';
        }

        saveReadingSettings();
    });

    // Переключение полноэкранного режима
    toggleFullscreenBtn.addEventListener('click', function() {
        toggleFullscreen(readingContainer);
    });

    // Слушатели событий для обновления состояния кнопки полноэкранного режима
    document.addEventListener('fullscreenchange', updateFullscreenButtonState);
    document.addEventListener('webkitfullscreenchange', updateFullscreenButtonState);
    document.addEventListener('mozfullscreenchange', updateFullscreenButtonState);
    document.addEventListener('MSFullscreenChange', updateFullscreenButtonState);

    // Обработчик клавиши Escape для выхода из мобильного псевдо-полноэкранного режима
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && document.body.classList.contains('mobile-fullscreen-mode')) {
            document.body.classList.remove('mobile-fullscreen-mode');
            document.body.classList.remove('dark-mode');
            readingContainer.classList.remove('mobile-fullscreen');

            // Восстанавливаем видимость скрытых элементов
            document.querySelectorAll('header, footer, .breadcrumb, .btn-outline-primary').forEach(el => {
                if (el) el.style.display = '';
            });

            // Меняем иконку обратно на "расширить"
            toggleFullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
            toggleFullscreenBtn.title = 'Enter fullscreen';
        }
    });

    // Кнопка сохранения позиции
    saveButton.addEventListener('click', function() {
        saveScrollPosition();
    });

    // Добавление закладки
    addBookmarkBtn.addEventListener('click', function() {
        const scrollPosition = bookContent.scrollTop;
        const context = getContextAtCurrentPosition();

        // Показываем модальное окно для создания закладки
        const bookmarkModal = document.getElementById('bookmarkModal');
        document.getElementById('bookmarkContext').textContent = context;

        const modal = new bootstrap.Modal(bookmarkModal);
        modal.show();
    });

    // Сохранение закладки
    document.getElementById('saveBookmarkBtn').addEventListener('click', function() {
        const scrollPosition = bookContent.scrollTop;
        const context = getContextAtCurrentPosition();
        const name = document.getElementById('bookmarkName').value.trim() || `Position ${Math.round((scrollPosition / bookContent.scrollHeight) * 100)}%`;

        // Добавляем закладку
        bookmarks.push({
            name: name,
            position: scrollPosition,
            context: context,
            created: new Date().toISOString()
        });

        // Сохраняем закладки
        localStorage.setItem(`book_bookmarks_${bookId}`, JSON.stringify(bookmarks));

        // Закрываем модальное окно
        const modal = bootstrap.Modal.getInstance(document.getElementById('bookmarkModal'));
        modal.hide();

        // Обновляем список закладок
        updateBookmarksList();

        // Показываем сообщение
        showStatusMessage(`Bookmark added: ${name}`, 'success');
    });

    // Обработчик для кнопки оглавления
    if (contentsBtn) {
        contentsBtn.addEventListener('click', function() {
            createTableOfContents();
        });
    }

    // CSS для скроллируемого контейнера и обложки внутри
    const containerStyle = document.createElement('style');
    containerStyle.textContent = `
        .scroll-container {
            height: 70vh;
            overflow-y: auto;
            border: 1px solid #e3e6f0;
            border-radius: 6px;
            box-shadow: 0 0.15rem 0.35rem rgba(0, 0, 0, 0.05);
            padding: 20px;
            scroll-behavior: smooth;
            margin-bottom: 2rem;
        }
        
        .dark-mode.scroll-container {
            background-color: #2c2c2c;
            color: #f0f0f0;
            border-color: #444;
        }
        
        /* Обложка книги внутри контента */
        .content-book-header {
            margin-bottom: 30px;
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid #e3e6f0;
        }
        
        .dark-mode .content-book-header {
            border-bottom-color: #444;
        }
        
        .content-book-title {
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 20px;
        }
        
        .content-book-cover {
            margin: 0 auto 20px;
            max-width: 300px;
        }
        
        .content-cover-image {
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            box-shadow: 0 0.25rem 1rem rgba(0, 0, 0, 0.15);
        }
        
        /* Стилизация полосы прокрутки */
        .scroll-container::-webkit-scrollbar {
            width: 10px;
        }
        
        .scroll-container::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 6px;
        }
        
        .scroll-container::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 6px;
        }
        
        .scroll-container::-webkit-scrollbar-thumb:hover {
            background: #a1a1a1;
        }
        
        .dark-mode.scroll-container::-webkit-scrollbar-track {
            background: #333;
        }
        
        .dark-mode.scroll-container::-webkit-scrollbar-thumb {
            background: #666;
        }
        
        .dark-mode.scroll-container::-webkit-scrollbar-thumb:hover {
            background: #888;
        }
        
        @media (max-width: 767.98px) {
            .scroll-container {
                height: 60vh;
            }
            
            .content-book-title {
                font-size: 1.5rem;
            }
            
            .content-book-cover {
                max-width: 200px;
            }
        }
        
        /* Улучшенные стили для мобильного полноэкранного режима */
        .mobile-fullscreen-mode {
            overflow: hidden !important;
            position: fixed;
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            background: white;
            transition: all 0.3s ease;
        }

        .mobile-fullscreen-mode.dark-mode {
            background: #1a1a1a;
        }

        .mobile-fullscreen-mode .reading-container {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            width: 100vw;
            height: 100vh;
            margin: 0;
            padding: 0;
            z-index: 9999;
            background-color: white;
            overflow: hidden;
            max-width: none;
        }

        .mobile-fullscreen-mode.dark-mode .reading-container {
            background-color: #1a1a1a;
        }

        /* Полностью скрываем тулбар в полноэкранном режиме */
        .mobile-fullscreen-mode .reading-toolbar {
            display: none !important;
        }

        /* Максимальный полноэкранный контент - только текст */
        .mobile-fullscreen-mode #book-content.scroll-container {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            height: 100vh !important;
            max-height: 100vh !important;
            width: 100vw !important;
            margin: 0 !important;
            padding: 15px !important;
            padding-top: 25px !important;
            padding-bottom: 25px !important;
            overflow-y: auto !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            background: transparent !important;
            font-size: 22px !important;
            line-height: 1.7 !important;
            max-width: none !important;
        }

        /* Увеличенный и оптимизированный текст */
        .mobile-fullscreen-mode #book-content p {
            font-size: 1.2em !important;
            margin-bottom: 1.8em !important;
            text-align: justify !important;
            color: inherit !important;
        }

        .mobile-fullscreen-mode #book-content h1,
        .mobile-fullscreen-mode #book-content h2,
        .mobile-fullscreen-mode #book-content h3 {
            margin-top: 2em !important;
            margin-bottom: 1em !important;
        }

        /* Полностью скрываем контролы */
        .mobile-fullscreen-mode #reading-controls {
            display: none !important;
        }

        /* Скрываем прогресс-бар */
        .mobile-fullscreen-mode .progress.mb-4 {
            display: none !important;
        }

        /* Скрытие ВСЕХ лишних элементов в полноэкранном режиме */
        .mobile-fullscreen-mode .breadcrumb,
        .mobile-fullscreen-mode .book-header,
        .mobile-fullscreen-mode .progress.mb-4,
        .mobile-fullscreen-mode .reading-toolbar,
        .mobile-fullscreen-mode #reading-controls {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* Минималистичная кнопка выхода */
        #mobile-exit-fullscreen {
            position: fixed !important;
            top: 10px !important;
            right: 10px !important;
            z-index: 10001 !important;
            background-color: rgba(0, 0, 0, 0.6) !important;
            color: white !important;
            border: none !important;
            border-radius: 50% !important;
            width: 36px !important;
            height: 36px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 14px !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
            opacity: 0.7 !important;
        }

        .mobile-fullscreen-mode.dark-mode #mobile-exit-fullscreen {
            background-color: rgba(255, 255, 255, 0.3) !important;
        }

        #mobile-exit-fullscreen:hover,
        #mobile-exit-fullscreen:active {
            opacity: 1 !important;
            transform: scale(1.1) !important;
        }

        /* Убираем отступы контейнера */
        .mobile-fullscreen-mode .reading-container {
            padding: 0 !important;
            margin: 0 !important;
        }
    `;
    document.head.appendChild(containerStyle);

    // Инициализация
    processBookContent();
    restoreReadingSettings();
    setupScrollableContainer();
    updateBookmarksList();
    updateProgressBar();
});