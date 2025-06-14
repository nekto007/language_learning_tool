/**
 * Mobile Reader JavaScript - Полностью оптимизировано для мобильного чтения
 * Приоритет: Mobile First, Performance, UX
 */

class MobileReader {
    constructor() {
        this.bookId = null;
        this.currentPosition = 0;
        this.totalWords = 0;
        this.settings = {
            fontSize: 18,
            fontFamily: 'Georgia, serif',
            isDarkMode: false,
            autoHideControls: true,
            tapToTranslate: true
        };
        this.bookmarks = [];
        this.isFullscreen = false;
        this.hideControlsTimeout = null;
        this.lastScrollPosition = 0;
        this.scrollDirection = 'down';
        this.lastSaveTime = 0;
        this.saveTimeout = null;
        this.lastSavedPosition = 0;
        
        this.init();
    }

    init() {
        this.loadElements();
        this.loadBookData();
        this.loadSettings();
        this.loadBookmarks();
        this.bindEvents();
        this.processContent();
        this.updateProgress();
        this.startAutoSave();
        this.loadCSRFToken();
        
        console.log('Mobile Reader initialized');
    }

    loadCSRFToken() {
        // Get CSRF token from meta tag
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        this.csrfToken = csrfToken ? csrfToken.getAttribute('content') : null;
        
        if (!this.csrfToken) {
            console.warn('CSRF token not found in page');
        } else {
            console.log('CSRF token loaded successfully');
        }
    }

    loadElements() {
        // Main containers
        this.reader = document.getElementById('mobileReader');
        this.header = document.getElementById('readerHeader');
        this.controls = document.getElementById('readerControls');
        this.content = document.getElementById('readingContent');
        this.progressBar = document.getElementById('progressFill');
        
        // Menu elements
        this.sideMenu = document.getElementById('sideMenu');
        this.menuOverlay = document.getElementById('menuOverlay');
        this.bookmarksList = document.getElementById('bookmarksList');
        
        // Controls
        this.menuBtn = document.getElementById('menuBtn');
        this.closeSideMenu = document.getElementById('closeSideMenu');
        this.fullscreenBtn = document.getElementById('fullscreenBtn');
        this.fullscreenExit = document.getElementById('fullscreenExit');
        
        // Settings controls
        this.fontSizeDisplay = document.getElementById('fontSize');
        this.increaseFontBtn = document.getElementById('increaseFont');
        this.decreaseFontBtn = document.getElementById('decreaseFont');
        this.darkModeToggle = document.getElementById('darkModeToggle');
        
        // Progress displays
        this.progressPercent = document.getElementById('progressPercent');
        this.currentPositionDisplay = document.getElementById('currentPosition');
        this.progressCircle = document.querySelector('.progress-circle');
        
        // Word popup
        this.wordPopup = document.getElementById('wordPopup');
        this.popupWord = document.getElementById('popupWord');
        this.popupTranslation = document.getElementById('popupTranslation');
        this.wordFormInfo = document.getElementById('wordFormInfo');
        this.playAudioBtn = document.getElementById('playAudio');
        this.addToLearningBtn = document.getElementById('addToLearning');
        this.closePopupBtn = document.getElementById('closePopup');
        
        // Log if any popup elements are missing
        if (!this.wordPopup) console.error('wordPopup element not found!');
        if (!this.popupWord) console.error('popupWord element not found!');
        if (!this.popupTranslation) console.error('popupTranslation element not found!');
        
        // Bookmark modal
        this.bookmarkModal = document.getElementById('bookmarkModal');
        this.addBookmarkBtn = document.getElementById('addBookmarkBtn');
        this.bookmarkNameInput = document.getElementById('bookmarkName');
        this.bookmarkContext = document.getElementById('bookmarkContext');
        this.saveBookmarkBtn = document.getElementById('saveBookmark');
        this.cancelBookmarkBtn = document.getElementById('cancelBookmark');
        this.closeBookmarkModal = document.getElementById('closeBookmarkModal');
        
        // Loading
        this.loading = document.getElementById('loading');
    }

    loadBookData() {
        this.bookId = this.content.getAttribute('data-book-id');
        this.currentPosition = parseInt(this.content.getAttribute('data-position')) || 0;
        this.lastSavedPosition = this.currentPosition; // Initialize saved position
        
        // Restore scroll position if exists
        if (this.currentPosition > 0) {
            this.content.scrollTop = this.currentPosition;
        }
    }

    loadSettings() {
        const savedSettings = localStorage.getItem(`mobile_reader_settings_${this.bookId}`);
        if (savedSettings) {
            this.settings = { ...this.settings, ...JSON.parse(savedSettings) };
        }
        
        this.applySettings();
    }

    applySettings() {
        // Apply font size
        this.content.style.setProperty('--reader-font-size', `${this.settings.fontSize}px`);
        this.fontSizeDisplay.textContent = `${this.settings.fontSize}px`;
        
        // Apply dark mode
        if (this.settings.isDarkMode) {
            document.documentElement.setAttribute('data-theme', 'dark');
            this.darkModeToggle.checked = true;
        } else {
            document.documentElement.removeAttribute('data-theme');
            this.darkModeToggle.checked = false;
        }
    }

    saveSettings() {
        localStorage.setItem(`mobile_reader_settings_${this.bookId}`, JSON.stringify(this.settings));
    }

    loadBookmarks() {
        const savedBookmarks = localStorage.getItem(`mobile_reader_bookmarks_${this.bookId}`);
        if (savedBookmarks) {
            this.bookmarks = JSON.parse(savedBookmarks);
        }
        this.updateBookmarksList();
    }

    saveBookmarks() {
        localStorage.setItem(`mobile_reader_bookmarks_${this.bookId}`, JSON.stringify(this.bookmarks));
    }

    bindEvents() {
        // Menu controls
        this.menuBtn.addEventListener('click', () => this.openSideMenu());
        this.closeSideMenu.addEventListener('click', () => this.closeSideMenuAction());
        this.menuOverlay.addEventListener('click', () => this.closeSideMenuAction());
        
        // Fullscreen controls
        this.fullscreenBtn.addEventListener('click', () => this.toggleFullscreen());
        this.fullscreenExit.addEventListener('click', () => this.exitFullscreen());
        
        // Settings controls
        this.increaseFontBtn.addEventListener('click', () => this.increaseFontSize());
        this.decreaseFontBtn.addEventListener('click', () => this.decreaseFontSize());
        this.darkModeToggle.addEventListener('change', () => this.toggleDarkMode());
        
        // Scroll events
        this.content.addEventListener('scroll', () => this.handleScroll());
        
        // Touch events for auto-hide controls
        this.content.addEventListener('touchstart', () => this.showControls());
        this.content.addEventListener('touchmove', () => this.handleTouchMove());
        
        // Word popup events
        this.closePopupBtn.addEventListener('click', () => this.hideWordPopup());
        this.playAudioBtn.addEventListener('click', () => this.playWordAudio());
        this.addToLearningBtn.addEventListener('click', () => this.addWordToLearning());
        
        // Bookmark events
        this.addBookmarkBtn.addEventListener('click', () => this.showAddBookmarkModal());
        this.saveBookmarkBtn.addEventListener('click', () => this.saveBookmark());
        this.cancelBookmarkBtn.addEventListener('click', () => this.hideAddBookmarkModal());
        this.closeBookmarkModal.addEventListener('click', () => this.hideAddBookmarkModal());
        
        // Keyboard events
        document.addEventListener('keydown', (e) => this.handleKeyboard(e));
        
        // Prevent zoom on double tap
        let lastTouchEnd = 0;
        this.content.addEventListener('touchend', (e) => {
            const now = new Date().getTime();
            if (now - lastTouchEnd <= 300) {
                e.preventDefault();
            }
            lastTouchEnd = now;
        }, false);
        
        // Handle orientation change
        window.addEventListener('orientationchange', () => {
            setTimeout(() => this.handleOrientationChange(), 100);
        });
        
        // Handle window resize for popup repositioning
        window.addEventListener('resize', () => {
            if (this.wordPopup.classList.contains('active')) {
                this.hideWordPopup();
            }
        });
        
        // Handle visibility change for auto-save
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.savePosition();
            }
        });
    }

    processContent() {
        console.log('Processing content...');
        const textElements = this.content.querySelectorAll('p, h1, h2, h3, h4, h5, h6');
        console.log('Found text elements:', textElements.length);
        
        textElements.forEach((element, index) => {
            if (element.getAttribute('data-processed')) {
                console.log(`Element ${index} already processed`);
                return;
            }
            
            const text = element.innerHTML;
            console.log(`Processing element ${index} with text:`, text.substring(0, 100));
            
            // Wrap English words in spans for translation
            const processedText = text.replace(
                /\b([a-zA-Z]{2,})\b(?![^<]*>|[^<>]*<\/)/g, 
                '<span class="word" data-word="$1">$1</span>'
            );
            
            console.log('Processed text (first 100 chars):', processedText.substring(0, 100));
            
            element.innerHTML = processedText;
            element.setAttribute('data-processed', 'true');
        });
        
        // Count processed words
        const wordElements = this.content.querySelectorAll('.word');
        console.log('Total word elements created:', wordElements.length);
        
        // Add click handlers to words
        this.content.addEventListener('click', (e) => {
            console.log('Click detected on element:', e.target);
            console.log('Element classes:', e.target.className);
            console.log('Element has word class:', e.target.classList.contains('word'));
            
            if (e.target.classList.contains('word')) {
                e.preventDefault();
                console.log('Word clicked:', e.target.textContent);
                this.handleWordClick(e.target);
            }
        });
    }

    handleWordClick(wordElement) {
        const word = wordElement.getAttribute('data-word').toLowerCase();
        console.log('handleWordClick called with word:', word);
        console.log('Element dataset:', wordElement.dataset);
        this.showWordTranslation(word, wordElement);
    }

    async showWordTranslation(word, element) {
        this.showLoading();
        
        try {
            console.log('Requesting translation for word:', word);
            
            const response = await fetch(`/api/word-translation/${encodeURIComponent(word)}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            
            console.log('Response status:', response.status);
            console.log('Response headers:', Object.fromEntries(response.headers.entries()));
            
            // Проверяем статус ответа
            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error('Требуется авторизация');
                } else if (response.status === 404) {
                    throw new Error('API не найдено');
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            // Проверяем тип контента
            const contentType = response.headers.get('content-type');
            console.log('Content-Type:', contentType);
            
            if (!contentType || !contentType.includes('application/json')) {
                const text = await response.text();
                console.error('Expected JSON but got:', contentType);
                console.error('Response text (first 500 chars):', text.substring(0, 500));
                
                // Если это HTML с redirect на login
                if (text.includes('<!doctype') || text.includes('<html')) {
                    throw new Error('Требуется авторизация (перенаправление на login)');
                }
                
                throw new Error('Сервер вернул неправильный тип данных');
            }
            
            const data = await response.json();
            this.hideLoading();
            
            console.log('Translation response:', data);
            
            if (data && data.translation) {
                this.displayWordPopup(data, element);
            } else if (data && data.in_dictionary === false) {
                this.showMessage('Слово не найдено в словаре', 'warning');
            } else {
                this.showMessage('Перевод не найден', 'warning');
            }
        } catch (error) {
            this.hideLoading();
            console.error('Translation error:', error);
            
            // Показываем fallback popup с просто словом
            this.displayFallbackWordPopup(word, element);
            
            if (error.message.includes('Failed to fetch')) {
                this.showMessage('Проблема с сетью', 'warning');
            } else if (error.message.includes('авторизация') || error.message.includes('login')) {
                this.showMessage('Требуется авторизация. Перезагрузите страницу.', 'warning');
            } else if (error.message.includes('JSON')) {
                this.showMessage('Ошибка формата данных', 'warning');
            } else {
                this.showMessage(`Ошибка: ${error.message}`, 'warning');
            }
        }
    }

    displayWordPopup(data, element) {
        console.log('Displaying word popup with data:', data);
        console.log('Element clicked:', element);
        
        // Check if popup elements exist
        if (!this.wordPopup || !this.popupWord || !this.popupTranslation) {
            console.error('Word popup elements not found!', {
                wordPopup: this.wordPopup,
                popupWord: this.popupWord,
                popupTranslation: this.popupTranslation
            });
            return;
        }
        
        // Hide any existing popup first
        this.hideWordPopup();
        
        // Highlight the word
        document.querySelectorAll('.word.selected').forEach(w => w.classList.remove('selected'));
        element.classList.add('selected');
        
        this.popupWord.textContent = data.word;
        this.popupTranslation.textContent = data.translation;
        
        console.log('Set popup text - word:', data.word, 'translation:', data.translation);
        
        // Show form information if available
        if (data.is_form && data.form_text && data.base_form) {
            this.wordFormInfo.textContent = `${data.form_text} "${data.base_form}"`;
            this.wordFormInfo.style.display = 'block';
        } else {
            this.wordFormInfo.style.display = 'none';
        }
        
        // Show audio button if available
        if (data.has_audio && data.audio_url) {
            this.playAudioBtn.style.display = 'block';
            this.playAudioBtn.setAttribute('data-audio-url', data.audio_url);
        } else {
            this.playAudioBtn.style.display = 'none';
        }
        
        // Show add to learning button if word is new
        if (data.status === 0) {
            this.addToLearningBtn.style.display = 'block';
            this.addToLearningBtn.setAttribute('data-word-id', data.id);
        } else {
            this.addToLearningBtn.style.display = 'none';
        }
        
        // Reset display first
        this.wordPopup.style.display = 'flex';
        this.wordPopup.style.visibility = 'visible';
        this.wordPopup.style.opacity = '1';
        
        // Position popup properly for desktop/mobile
        this.positionWordPopup(element);
        
        // Force a reflow to ensure positioning is calculated
        this.wordPopup.offsetHeight;
        
        // Show popup with animation
        console.log('About to add active class to popup');
        console.log('Popup before adding active class:', {
            className: this.wordPopup.className,
            style: this.wordPopup.style.cssText,
            offsetTop: this.wordPopup.offsetTop,
            offsetLeft: this.wordPopup.offsetLeft
        });
        
        this.wordPopup.classList.add('active');
        console.log('Added active class to word popup');
        console.log('Popup after adding active class:', {
            className: this.wordPopup.className,
            style: this.wordPopup.style.cssText
        });
        
        // Additional debugging: Force popup to be visible for testing
        if (window.innerWidth <= 768) {
            // Mobile: force bottom position
            this.wordPopup.style.bottom = '0px';
            console.log('Mobile: Forced popup to bottom');
        }
        
        // Check styles with a slight delay to ensure CSS has been applied
        setTimeout(() => {
            console.log('Popup styles after adding active:', {
                display: getComputedStyle(this.wordPopup).display,
                visibility: getComputedStyle(this.wordPopup).visibility,
                opacity: getComputedStyle(this.wordPopup).opacity,
                position: getComputedStyle(this.wordPopup).position,
                zIndex: getComputedStyle(this.wordPopup).zIndex,
                top: getComputedStyle(this.wordPopup).top,
                left: getComputedStyle(this.wordPopup).left,
                bottom: getComputedStyle(this.wordPopup).bottom,
                right: getComputedStyle(this.wordPopup).right
            });
            
            const rect = this.wordPopup.getBoundingClientRect();
            console.log('Popup bounding rect:', rect);
            console.log('Viewport dimensions:', {
                width: window.innerWidth,
                height: window.innerHeight
            });
        }, 100);
        
        // Auto-play audio if available
        if (data.has_audio && data.audio_url) {
            setTimeout(() => {
                this.playAudio(data.audio_url);
            }, 500);
        }
    }
    
    positionWordPopup(element) {
        console.log('Positioning popup. Screen width:', window.innerWidth);
        
        // For mobile devices (width <= 768px), use bottom sheet - no additional positioning needed
        if (window.innerWidth <= 768) {
            console.log('Mobile layout: using bottom sheet positioning');
            // Reset any desktop positioning
            this.wordPopup.style.position = 'fixed';
            this.wordPopup.style.top = '';
            this.wordPopup.style.left = '';
            this.wordPopup.style.right = '';
            this.wordPopup.style.bottom = '-100%';
            return;
        }
        
        // Desktop positioning - use fixed positioning relative to viewport
        console.log('Desktop layout: positioning near word');
        const rect = element.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        // Use fixed positioning relative to viewport
        this.wordPopup.style.position = 'fixed';
        
        // Calculate initial position
        let topPosition = rect.bottom + 5; // Position below the word
        let leftPosition = rect.left;
        
        // Ensure popup fits horizontally
        const popupWidth = 300; // Approximate popup width
        if (leftPosition + popupWidth > viewportWidth) {
            leftPosition = viewportWidth - popupWidth - 10;
        }
        if (leftPosition < 10) {
            leftPosition = 10;
        }
        
        // Ensure popup fits vertically
        const popupHeight = 200; // Approximate popup height
        if (topPosition + popupHeight > viewportHeight) {
            // Position above the word instead
            topPosition = rect.top - popupHeight - 5;
            // If it still doesn't fit, position at top of viewport
            if (topPosition < 10) {
                topPosition = 10;
            }
        }
        
        this.wordPopup.style.top = `${topPosition}px`;
        this.wordPopup.style.left = `${leftPosition}px`;
        this.wordPopup.style.bottom = '';
        this.wordPopup.style.right = '';
        
        console.log('Desktop popup positioned at:', {
            top: this.wordPopup.style.top,
            left: this.wordPopup.style.left,
            elementRect: rect,
            viewport: { width: viewportWidth, height: viewportHeight }
        });
    }

    displayFallbackWordPopup(word, element) {
        // Highlight the word
        document.querySelectorAll('.word.selected').forEach(w => w.classList.remove('selected'));
        element.classList.add('selected');
        
        this.popupWord.textContent = word;
        this.popupTranslation.textContent = 'Перевод недоступен (проблема с подключением)';
        
        // Hide all optional elements
        this.wordFormInfo.style.display = 'none';
        this.playAudioBtn.style.display = 'none';
        this.addToLearningBtn.style.display = 'none';
        
        // Position popup properly for desktop/mobile
        this.positionWordPopup(element);
        
        // Show popup with animation
        this.wordPopup.classList.add('active');
    }

    hideWordPopup() {
        this.wordPopup.classList.remove('active');
        document.querySelectorAll('.word.selected').forEach(w => w.classList.remove('selected'));
        
        // Reset all positioning and visibility styles
        this.wordPopup.style.position = '';
        this.wordPopup.style.top = '';
        this.wordPopup.style.left = '';
        this.wordPopup.style.bottom = '';
        this.wordPopup.style.right = '';
        this.wordPopup.style.transform = '';
        this.wordPopup.style.display = '';
        this.wordPopup.style.visibility = '';
        this.wordPopup.style.opacity = '';
        
        console.log('Word popup hidden');
    }

    playWordAudio() {
        const audioUrl = this.playAudioBtn.getAttribute('data-audio-url');
        console.log('Play audio button clicked, URL:', audioUrl);
        if (audioUrl) {
            this.playAudio(audioUrl);
        } else {
            console.warn('No audio URL found for playback');
        }
    }

    playAudio(audioUrl) {
        console.log('Playing audio from URL:', audioUrl);
        const audio = new Audio(audioUrl);
        
        audio.addEventListener('loadstart', () => console.log('Audio loading started'));
        audio.addEventListener('canplay', () => console.log('Audio can start playing'));
        audio.addEventListener('error', (e) => console.error('Audio error:', e));
        
        audio.play().then(() => {
            console.log('Audio playback started successfully');
        }).catch(error => {
            console.error('Audio playback failed:', error);
        });
    }

    async addWordToLearning() {
        const wordId = this.addToLearningBtn.getAttribute('data-word-id');
        if (!wordId) return;
        
        this.showLoading();
        
        try {
            const headers = { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch('/api/add-to-learning', {
                method: 'POST',
                headers: headers,
                credentials: 'same-origin',
                body: JSON.stringify({ word_id: parseInt(wordId) })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                const text = await response.text();
                console.error('Expected JSON but got:', contentType, text.substring(0, 200));
                throw new Error('Сервер вернул неправильный тип данных');
            }
            
            const data = await response.json();
            this.hideLoading();
            
            console.log('Add to learning response:', data);
            
            if (data.success) {
                this.addToLearningBtn.style.display = 'none';
                this.showMessage(data.message || 'Слово добавлено в изучение', 'success');
            } else {
                this.showMessage(data.error || 'Ошибка добавления слова', 'error');
            }
        } catch (error) {
            this.hideLoading();
            console.error('Add to learning error:', error);
            
            if (error.message.includes('Failed to fetch')) {
                this.showMessage('Проблема с сетью', 'error');
            } else if (error.message.includes('JSON')) {
                this.showMessage('Ошибка формата данных', 'error');
            } else {
                this.showMessage(`Ошибка: ${error.message}`, 'error');
            }
        }
    }

    handleScroll() {
        const scrollTop = this.content.scrollTop;
        const scrollHeight = this.content.scrollHeight - this.content.clientHeight;
        const progress = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
        
        this.updateProgressDisplay(progress);
        this.currentPosition = scrollTop;
        
        // Determine scroll direction
        if (scrollTop > this.lastScrollPosition) {
            this.scrollDirection = 'down';
        } else {
            this.scrollDirection = 'up';
        }
        this.lastScrollPosition = scrollTop;
        
        // Auto-hide controls when scrolling down
        if (this.settings.autoHideControls && !this.isFullscreen) {
            if (this.scrollDirection === 'down') {
                this.hideControls();
            } else {
                this.showControls();
            }
        }
        
        // Debounced save with rate limiting
        this.debouncedSave();
    }

    updateProgressDisplay(progress) {
        this.progressBar.style.width = `${progress}%`;
        this.progressPercent.textContent = `${Math.round(progress)}%`;
        this.currentPositionDisplay.textContent = Math.round(this.currentPosition);
        
        // Update progress circle
        if (this.progressCircle) {
            const angle = (progress / 100) * 360;
            this.progressCircle.style.background = 
                `conic-gradient(var(--primary-color) ${angle}deg, var(--border-color) ${angle}deg)`;
        }
    }

    showControls() {
        this.header.classList.remove('hidden');
        this.controls.classList.remove('hidden');
        
        clearTimeout(this.hideControlsTimeout);
        if (this.settings.autoHideControls && !this.isFullscreen) {
            this.hideControlsTimeout = setTimeout(() => this.hideControls(), 3000);
        }
    }

    hideControls() {
        if (!this.isFullscreen) return;
        
        this.header.classList.add('hidden');
        this.controls.classList.add('hidden');
    }

    handleTouchMove() {
        this.showControls();
    }

    increaseFontSize() {
        if (this.settings.fontSize < 32) {
            this.settings.fontSize += 2;
            this.applySettings();
            this.saveSettings();
        }
    }

    decreaseFontSize() {
        if (this.settings.fontSize > 12) {
            this.settings.fontSize -= 2;
            this.applySettings();
            this.saveSettings();
        }
    }

    toggleDarkMode() {
        this.settings.isDarkMode = this.darkModeToggle.checked;
        this.applySettings();
        this.saveSettings();
    }

    openSideMenu() {
        this.sideMenu.classList.add('open');
        this.menuOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    closeSideMenuAction() {
        this.sideMenu.classList.remove('open');
        this.menuOverlay.classList.remove('active');
        document.body.style.overflow = '';
    }

    toggleFullscreen() {
        if (this.isFullscreen) {
            this.exitFullscreen();
        } else {
            this.enterFullscreen();
        }
    }

    enterFullscreen() {
        this.reader.classList.add('fullscreen');
        this.fullscreenExit.style.display = 'flex';
        this.fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i><span>Выйти</span>';
        this.isFullscreen = true;
        
        // Hide address bar on mobile
        if (window.screen && window.screen.orientation) {
            setTimeout(() => {
                window.scrollTo(0, 1);
            }, 100);
        }
    }

    exitFullscreen() {
        this.reader.classList.remove('fullscreen');
        this.fullscreenExit.style.display = 'none';
        this.fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i><span>Полный экран</span>';
        this.isFullscreen = false;
        this.showControls();
    }

    showAddBookmarkModal() {
        const context = this.getCurrentContext();
        this.bookmarkContext.textContent = context;
        this.bookmarkNameInput.value = `Позиция ${Math.round((this.currentPosition / (this.content.scrollHeight - this.content.clientHeight)) * 100)}%`;
        this.bookmarkModal.classList.add('active');
        this.bookmarkNameInput.focus();
    }

    hideAddBookmarkModal() {
        this.bookmarkModal.classList.remove('active');
        this.bookmarkNameInput.value = '';
    }

    getCurrentContext() {
        const viewportTop = this.content.scrollTop;
        const elements = this.content.querySelectorAll('p, h1, h2, h3, h4, h5, h6');
        
        for (let el of elements) {
            if (el.offsetTop >= viewportTop) {
                let context = el.textContent.trim();
                if (context.length > 100) {
                    context = context.substring(0, 100) + '...';
                }
                return context;
            }
        }
        
        return 'Текущая позиция';
    }

    saveBookmark() {
        const name = this.bookmarkNameInput.value.trim();
        if (!name) return;
        
        const bookmark = {
            id: Date.now(),
            name: name,
            position: this.currentPosition,
            context: this.bookmarkContext.textContent,
            created: new Date().toISOString()
        };
        
        this.bookmarks.push(bookmark);
        this.saveBookmarks();
        this.updateBookmarksList();
        this.hideAddBookmarkModal();
        this.showMessage('Закладка добавлена', 'success');
    }

    updateBookmarksList() {
        if (this.bookmarks.length === 0) {
            this.bookmarksList.innerHTML = '<p class="no-bookmarks">Нет закладок</p>';
            return;
        }
        
        this.bookmarksList.innerHTML = this.bookmarks.map(bookmark => `
            <div class="bookmark-item" data-position="${bookmark.position}">
                <div class="bookmark-title">${bookmark.name}</div>
                <div class="bookmark-context">${bookmark.context}</div>
                <button class="btn-delete-bookmark" data-id="${bookmark.id}">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `).join('');
        
        // Add click handlers
        this.bookmarksList.querySelectorAll('.bookmark-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.btn-delete-bookmark')) {
                    const position = parseInt(item.getAttribute('data-position'));
                    this.goToPosition(position);
                    this.closeSideMenuAction();
                }
            });
        });
        
        this.bookmarksList.querySelectorAll('.btn-delete-bookmark').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const id = parseInt(btn.getAttribute('data-id'));
                this.deleteBookmark(id);
            });
        });
    }

    deleteBookmark(id) {
        this.bookmarks = this.bookmarks.filter(b => b.id !== id);
        this.saveBookmarks();
        this.updateBookmarksList();
        this.showMessage('Закладка удалена', 'info');
    }

    goToPosition(position) {
        this.content.scrollTo({
            top: position,
            behavior: 'smooth'
        });
    }

    debouncedSave() {
        // Clear any existing timeout
        clearTimeout(this.saveTimeout);
        
        // Only save if position has changed significantly (> 50px)
        const positionDifference = Math.abs(this.currentPosition - this.lastSavedPosition);
        if (positionDifference < 50) {
            return;
        }
        
        // Set a debounced save with 2 second delay
        this.saveTimeout = setTimeout(() => {
            this.savePosition();
        }, 2000);
    }

    async savePosition() {
        if (!this.bookId) return;
        
        // Rate limiting: don't save more than once every 5 seconds
        const now = Date.now();
        const timeSinceLastSave = now - this.lastSaveTime;
        if (timeSinceLastSave < 5000) {
            console.log('Rate limiting: skipping save (too soon)');
            return;
        }
        
        // Don't save if position hasn't changed
        if (this.currentPosition === this.lastSavedPosition) {
            console.log('Position unchanged, skipping save');
            return;
        }
        
        try {
            const headers = { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            console.log(`Saving position: ${this.currentPosition}`);
            
            const response = await fetch('/api/save-reading-position', {
                method: 'POST',
                headers: headers,
                credentials: 'same-origin',
                body: JSON.stringify({
                    book_id: parseInt(this.bookId),
                    position: this.currentPosition
                })
            });
            
            if (response.ok) {
                this.lastSaveTime = now;
                this.lastSavedPosition = this.currentPosition;
                console.log('Position saved successfully');
            } else {
                console.error('Save position failed:', response.status, response.statusText);
                
                // If we get 429 (Too Many Requests), increase the rate limit
                if (response.status === 429) {
                    console.warn('Rate limited by server. Will retry in 10 seconds.');
                    setTimeout(() => {
                        this.savePosition();
                    }, 10000);
                }
            }
        } catch (error) {
            console.error('Save position error:', error);
        }
    }

    startAutoSave() {
        // Auto-save position every 60 seconds (reduced frequency)
        setInterval(() => {
            // Only auto-save if position has changed since last save
            if (this.currentPosition !== this.lastSavedPosition) {
                this.savePosition();
            }
        }, 60000);
    }

    handleKeyboard(e) {
        // ESC key - close popups/menus
        if (e.key === 'Escape') {
            if (this.wordPopup.classList.contains('active')) {
                this.hideWordPopup();
            } else if (this.sideMenu.classList.contains('open')) {
                this.closeSideMenuAction();
            } else if (this.bookmarkModal.classList.contains('active')) {
                this.hideAddBookmarkModal();
            } else if (this.isFullscreen) {
                this.exitFullscreen();
            }
        }
        
        // Space or F key - toggle fullscreen (only if no modifiers are pressed)
        if ((e.key === ' ' || e.key === 'f') && !e.target.closest('input') && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            this.toggleFullscreen();
        }
    }

    handleOrientationChange() {
        // Recalculate layout after orientation change
        setTimeout(() => this.updateProgress(), 300);
    }

    updateProgress() {
        const scrollTop = this.content.scrollTop;
        const scrollHeight = this.content.scrollHeight - this.content.clientHeight;
        const progress = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
        this.updateProgressDisplay(progress);
    }

    showLoading() {
        this.loading.style.display = 'flex';
    }

    hideLoading() {
        this.loading.style.display = 'none';
    }

    showMessage(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--primary-color);
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            z-index: 3000;
            font-size: 14px;
            max-width: 80%;
            text-align: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.3s ease;
        `;
        
        if (type === 'error') {
            toast.style.background = '#e74c3c';
        } else if (type === 'success') {
            toast.style.background = '#1cc88a';
        } else if (type === 'warning') {
            toast.style.background = '#f39c12';
        }
        
        document.body.appendChild(toast);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(-50%) translateY(-20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.mobileReader = new MobileReader();
});

// Handle back button
window.addEventListener('popstate', () => {
    if (window.mobileReader && window.mobileReader.isFullscreen) {
        window.mobileReader.exitFullscreen();
    }
});