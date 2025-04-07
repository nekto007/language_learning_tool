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
    const fontSerifBtn = document.getElementById('font-serif');
    const fontSansBtn = document.getElementById('font-sans');
    const addBookmarkBtn = document.getElementById('add-bookmark');
    const bookmarksContainer = document.getElementById('bookmarks-container');
    const noBookmarksMsg = document.getElementById('no-bookmarks');
    const contentsBtn = document.getElementById('contents-btn');
    const bookHeader = document.querySelector('.book-header');
    const bookTitle = document.querySelector('.book-title').textContent;

    // Настройки
    let currentFontSize = parseInt(fontSizeValue.textContent) || 18;
    let isDarkMode = false;
    let bookmarks = JSON.parse(localStorage.getItem(`book_bookmarks_${bookId}`) || '[]');

    // Делаем контейнер книги скроллируемым с фиксированной высотой
    function setupScrollableContainer() {
        // Добавляем класс для скроллируемого контейнера
        bookContent.classList.add('scroll-container');

        // Добавляем кнопку для возврата к сохраненной позиции, если ее еще нет
        if (!document.getElementById('return-to-position')) {
            const returnButton = document.createElement('button');
            returnButton.id = 'return-to-position';
            returnButton.className = 'btn btn-sm btn-outline-primary ms-3';
            returnButton.innerHTML = '<i class="fas fa-bookmark"></i> Return to Last Position';

            // Вставляем кнопку в панель инструментов
            const toolbar = document.querySelector('.reading-toolbar');
            const firstGroup = toolbar.querySelector('.d-flex.align-items-center');
            if (firstGroup) {
                firstGroup.appendChild(returnButton);
            }

            // Обработчик для возврата к позиции
            returnButton.addEventListener('click', function() {
                restoreScrollPosition();
            });
        }

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

            // Более надежное скрытие оригинальной обложки в шапке
            // Используем несколько методов для большей надежности

            // Метод 1: Скрываем .book-header напрямую
            const bookHeader = document.querySelector('.book-header');
            if (bookHeader) {
                bookHeader.style.display = 'none';
                bookHeader.style.visibility = 'hidden';
                bookHeader.style.opacity = '0';
                bookHeader.style.height = '0';
                bookHeader.style.overflow = 'hidden';
            }

            // Метод 2: Добавляем CSS-правило в <style> для перекрытия всех возможных стилей
            const styleEl = document.createElement('style');
            styleEl.textContent = `
                .book-header {
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    height: 0 !important;
                    overflow: hidden !important;
                    margin: 0 !important;
                    padding: 0 !important;
                }
                
                .book-cover-container {
                    display: none !important;
                }
            `;
            document.head.appendChild(styleEl);

            // Метод 3: Полностью удаляем элемент из DOM, если это не нарушит структуру
            setTimeout(() => {
                const headerElem = document.querySelector('.book-header');
                if (headerElem && headerElem.parentNode) {
                    try {
                        headerElem.parentNode.removeChild(headerElem);
                    } catch (e) {
                        console.log("Couldn't remove header element, using CSS hiding instead");
                    }
                }
            }, 100);
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
        fetch(`/api/word-translation/${wordText}`)
            .then(response => response.json())
            .then(data => {
                if (data.translation) {
                    // Создаем индикатор статуса
                    const statusDot = document.createElement('span');
                    statusDot.className = `word-status status-${data.status || 0}`;

                    // Обновляем содержимое
                    tooltip.innerHTML = '';
                    tooltip.appendChild(statusDot);

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

                    // Добавляем кнопку "Learn" для новых слов
                    if (data.status === 0) {
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
                tooltip.textContent = 'Error loading translation';
                console.error('Error fetching translation:', error);
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
            this.innerHTML = '<i class="fas fa-sun"></i>';
        } else {
            bookContent.classList.remove('dark-mode');
            this.innerHTML = '<i class="fas fa-moon"></i>';
        }

        saveReadingSettings();
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
    `;
    document.head.appendChild(containerStyle);

    // Инициализация
    processBookContent();
    restoreReadingSettings();
    setupScrollableContainer();
    updateBookmarksList();
    updateProgressBar();
});