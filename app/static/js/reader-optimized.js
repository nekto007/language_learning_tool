/**
 * Optimized Reader JavaScript
 * Modern reading experience with enhanced features
 */

class OptimizedReader {
    constructor() {
        this.bookId = null;
        this.currentPosition = 0;
        this.fontSize = 18;
        this.isDarkTheme = false;
        this.isSerifFont = true;
        this.isFullscreen = false;
        this.isSidebarOpen = false;
        this.bookmarks = [];
        this.toc = [];
        
        this.init();
    }

    init() {
        this.bookId = document.getElementById('book-content')?.dataset.bookId;
        this.currentPosition = parseInt(document.getElementById('book-content')?.dataset.position || 0);
        
        this.setupEventListeners();
        this.loadSettings();
        this.makeWordsClickable();
        this.generateTableOfContents();
        this.loadBookmarks();
        this.updateProgress();
        this.restorePosition();
        
        // Auto-save position every 30 seconds
        setInterval(() => this.autoSavePosition(), 30000);
    }

    setupEventListeners() {
        // Sidebar controls
        document.getElementById('toggleSidebar')?.addEventListener('click', () => this.toggleSidebar());
        document.getElementById('closeSidebar')?.addEventListener('click', () => this.closeSidebar());

        // Font controls
        document.getElementById('decrease-font')?.addEventListener('click', () => this.changeFontSize(-2));
        document.getElementById('increase-font')?.addEventListener('click', () => this.changeFontSize(2));
        document.getElementById('toggle-font')?.addEventListener('click', () => this.toggleFontFamily());

        // Theme and display
        document.getElementById('toggle-theme')?.addEventListener('click', () => this.toggleTheme());
        document.getElementById('toggle-fullscreen')?.addEventListener('click', () => this.toggleFullscreen());

        // Position and bookmarks
        document.getElementById('save-position')?.addEventListener('click', () => this.savePosition());
        document.getElementById('addBookmark')?.addEventListener('click', () => this.showBookmarkModal());
        document.getElementById('save-bookmark')?.addEventListener('click', () => this.saveBookmark());

        // Scroll tracking for progress
        document.getElementById('reader-content')?.addEventListener('scroll', () => this.updateProgress());

        // Word translation popup
        document.addEventListener('click', (e) => this.handleDocumentClick(e));

        // Escape key to close sidebar/popup
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeSidebar();
                this.closeTranslationPopup();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyboardShortcuts(e));
    }

    // Sidebar Management
    toggleSidebar() {
        this.isSidebarOpen = !this.isSidebarOpen;
        const sidebar = document.getElementById('sidebar');
        if (this.isSidebarOpen) {
            sidebar.classList.add('open');
        } else {
            sidebar.classList.remove('open');
        }
    }

    closeSidebar() {
        this.isSidebarOpen = false;
        document.getElementById('sidebar').classList.remove('open');
    }

    // Font Management
    changeFontSize(delta) {
        this.fontSize = Math.max(12, Math.min(32, this.fontSize + delta));
        document.documentElement.style.setProperty('--reader-font-size', `${this.fontSize}px`);
        document.getElementById('font-size-display').textContent = `${this.fontSize}px`;
        this.saveSettings();
    }

    toggleFontFamily() {
        this.isSerifFont = !this.isSerifFont;
        document.body.style.fontFamily = this.isSerifFont ? 'Georgia, serif' : 'system-ui, sans-serif';
        this.saveSettings();
    }

    // Theme Management
    toggleTheme() {
        this.isDarkTheme = !this.isDarkTheme;
        document.documentElement.setAttribute('data-theme', this.isDarkTheme ? 'dark' : 'light');
        const icon = document.querySelector('#toggle-theme i');
        if (icon) {
            icon.className = this.isDarkTheme ? 'fas fa-sun' : 'fas fa-moon';
        }
        this.saveSettings();
    }

    // Fullscreen Management
    toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().then(() => {
                this.isFullscreen = true;
                document.querySelector('#toggle-fullscreen i').className = 'fas fa-compress';
            });
        } else {
            document.exitFullscreen().then(() => {
                this.isFullscreen = false;
                document.querySelector('#toggle-fullscreen i').className = 'fas fa-expand';
            });
        }
    }

    // Word Click Functionality
    makeWordsClickable() {
        const content = document.getElementById('book-content');
        if (!content) return;

        // Split text into clickable words
        const walker = document.createTreeWalker(
            content,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        const textNodes = [];
        let node;
        while (node = walker.nextNode()) {
            if (node.textContent.trim()) {
                textNodes.push(node);
            }
        }

        textNodes.forEach(textNode => {
            const words = textNode.textContent.split(/(\s+)/);
            if (words.length <= 1) return;

            const fragment = document.createDocumentFragment();
            words.forEach(word => {
                if (word.trim() && /[a-zA-Z]/.test(word)) {
                    const span = document.createElement('span');
                    span.className = 'word-clickable';
                    span.textContent = word;
                    span.addEventListener('click', (e) => this.handleWordClick(e, word.trim()));
                    fragment.appendChild(span);
                } else {
                    fragment.appendChild(document.createTextNode(word));
                }
            });

            textNode.parentNode.replaceChild(fragment, textNode);
        });
    }

    async handleWordClick(event, word) {
        event.stopPropagation();
        
        // Clean word (remove punctuation)
        const cleanWord = word.replace(/[^\w]/g, '').toLowerCase();
        
        try {
            const response = await fetch('/api/translate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ word: cleanWord })
            });

            if (response.ok) {
                const data = await response.json();
                this.showTranslationPopup(event, cleanWord, data.translation || 'Translation not found');
            }
        } catch (error) {
            console.error('Translation error:', error);
            this.showTranslationPopup(event, cleanWord, 'Translation unavailable');
        }
    }

    showTranslationPopup(event, word, translation) {
        const popup = document.getElementById('translation-popup');
        if (!popup) return;

        document.getElementById('popup-word').textContent = word;
        document.getElementById('popup-translation').textContent = translation;
        
        // Position popup near click
        const rect = event.target.getBoundingClientRect();
        popup.style.left = `${rect.left}px`;
        popup.style.top = `${rect.bottom + 10}px`;
        popup.style.display = 'block';

        // Store current word for learning
        popup.dataset.currentWord = word;
    }

    closeTranslationPopup() {
        const popup = document.getElementById('translation-popup');
        if (popup) {
            popup.style.display = 'none';
        }
    }

    handleDocumentClick(event) {
        const popup = document.getElementById('translation-popup');
        if (popup && !popup.contains(event.target) && !event.target.classList.contains('word-clickable')) {
            this.closeTranslationPopup();
        }
    }

    // Progress Management
    updateProgress() {
        const content = document.getElementById('reader-content');
        if (!content) return;

        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight - content.clientHeight;
        const progress = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;

        // Update progress bars
        document.getElementById('reading-progress').style.width = `${progress}%`;
        document.getElementById('progress-bar').style.width = `${progress}%`;
        document.getElementById('progress-percent').textContent = `${Math.round(progress)}%`;
        document.getElementById('current-position').textContent = Math.round(scrollTop);

        this.currentPosition = scrollTop;
    }

    // Position Management
    async savePosition() {
        if (!this.bookId) return;

        try {
            const response = await fetch('/api/save-reading-position', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    book_id: this.bookId,
                    position: this.currentPosition
                })
            });

            if (response.ok) {
                this.showMessage('Position saved successfully!', 'success');
            }
        } catch (error) {
            console.error('Save position error:', error);
            this.showMessage('Failed to save position', 'error');
        }
    }

    autoSavePosition() {
        this.savePosition();
    }

    restorePosition() {
        if (this.currentPosition > 0) {
            const content = document.getElementById('reader-content');
            if (content) {
                content.scrollTop = this.currentPosition;
            }
        }
    }

    // Table of Contents
    generateTableOfContents() {
        const content = document.getElementById('book-content');
        const tocContainer = document.getElementById('toc-container');
        if (!content || !tocContainer) return;

        const headings = content.querySelectorAll('h1, h2, h3, h4, h5, h6');
        this.toc = Array.from(headings).map((heading, index) => {
            const id = `toc-${index}`;
            heading.id = id;
            return {
                id,
                text: heading.textContent.trim(),
                level: parseInt(heading.tagName.charAt(1))
            };
        });

        tocContainer.innerHTML = this.toc.map(item => `
            <div class="toc-item" data-target="${item.id}" style="padding-left: ${(item.level - 1) * 1}rem">
                ${item.text}
            </div>
        `).join('');

        // Add click handlers
        tocContainer.querySelectorAll('.toc-item').forEach(item => {
            item.addEventListener('click', () => {
                const target = document.getElementById(item.dataset.target);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth' });
                    this.closeSidebar();
                }
            });
        });
    }

    // Bookmarks Management
    async loadBookmarks() {
        if (!this.bookId) return;

        try {
            const response = await fetch(`/api/bookmarks/${this.bookId}`);
            if (response.ok) {
                this.bookmarks = await response.json();
                this.renderBookmarks();
            }
        } catch (error) {
            console.error('Load bookmarks error:', error);
        }
    }

    renderBookmarks() {
        const container = document.getElementById('bookmarks-container');
        if (!container) return;

        if (this.bookmarks.length === 0) {
            container.innerHTML = '<div class="text-muted small">No bookmarks yet</div>';
            return;
        }

        container.innerHTML = this.bookmarks.map(bookmark => `
            <div class="bookmark-item" data-position="${bookmark.position}">
                <div class="bookmark-title">${bookmark.name}</div>
                <div class="bookmark-context">"${bookmark.context}"</div>
            </div>
        `).join('');

        // Add click handlers
        container.querySelectorAll('.bookmark-item').forEach(item => {
            item.addEventListener('click', () => {
                const position = parseInt(item.dataset.position);
                const content = document.getElementById('reader-content');
                if (content) {
                    content.scrollTop = position;
                    this.closeSidebar();
                }
            });
        });
    }

    showBookmarkModal() {
        // Get current context
        const selection = window.getSelection();
        let context = '';
        
        if (selection.rangeCount > 0) {
            context = selection.toString().trim();
        }
        
        if (!context) {
            // Get nearby text as context
            const content = document.getElementById('reader-content');
            const scrollPos = content.scrollTop;
            const textElements = content.querySelectorAll('p');
            
            for (let p of textElements) {
                const rect = p.getBoundingClientRect();
                if (rect.top >= 0 && rect.top <= 200) {
                    context = p.textContent.substring(0, 100) + '...';
                    break;
                }
            }
        }

        // Auto-generate bookmark name
        const bookmarkName = `Page ${Math.round(this.currentPosition / 1000) + 1}`;
        document.getElementById('bookmark-name').value = bookmarkName;

        // Show modal
        new bootstrap.Modal(document.getElementById('bookmarkModal')).show();
    }

    async saveBookmark() {
        const name = document.getElementById('bookmark-name').value.trim();
        if (!name) return;

        const bookmark = {
            book_id: this.bookId,
            name: name,
            position: this.currentPosition,
            context: this.getCurrentContext()
        };

        try {
            const response = await fetch('/api/bookmarks', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(bookmark)
            });

            if (response.ok) {
                this.showMessage('Bookmark saved!', 'success');
                bootstrap.Modal.getInstance(document.getElementById('bookmarkModal')).hide();
                this.loadBookmarks();
            }
        } catch (error) {
            console.error('Save bookmark error:', error);
            this.showMessage('Failed to save bookmark', 'error');
        }
    }

    getCurrentContext() {
        const content = document.getElementById('reader-content');
        const textElements = content.querySelectorAll('p');
        
        for (let p of textElements) {
            const rect = p.getBoundingClientRect();
            if (rect.top >= 0 && rect.top <= 200) {
                return p.textContent.substring(0, 150) + '...';
            }
        }
        return 'Current reading position';
    }

    // Settings Management
    saveSettings() {
        const settings = {
            fontSize: this.fontSize,
            isDarkTheme: this.isDarkTheme,
            isSerifFont: this.isSerifFont
        };
        localStorage.setItem('reader-settings', JSON.stringify(settings));
    }

    loadSettings() {
        const settings = JSON.parse(localStorage.getItem('reader-settings') || '{}');
        
        if (settings.fontSize) {
            this.fontSize = settings.fontSize;
            this.changeFontSize(0); // Apply font size
        }
        
        if (settings.isDarkTheme) {
            this.toggleTheme();
        }
        
        if (settings.isSerifFont !== undefined) {
            this.isSerifFont = settings.isSerifFont;
            this.toggleFontFamily();
        }
    }

    // Keyboard Shortcuts
    handleKeyboardShortcuts(event) {
        if (event.ctrlKey || event.metaKey) {
            switch (event.key) {
                case 's':
                    event.preventDefault();
                    this.savePosition();
                    break;
                case 'b':
                    event.preventDefault();
                    this.showBookmarkModal();
                    break;
                case 'd':
                    event.preventDefault();
                    this.toggleTheme();
                    break;
                case '[':
                    event.preventDefault();
                    this.changeFontSize(-2);
                    break;
                case ']':
                    event.preventDefault();
                    this.changeFontSize(2);
                    break;
            }
        }
        
        if (event.key === 'F11') {
            event.preventDefault();
            this.toggleFullscreen();
        }
    }

    // Utility Methods
    getCSRFToken() {
        return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
    }

    showMessage(message, type = 'info') {
        // Create toast notification
        const toast = document.createElement('div');
        toast.className = `alert alert-${type === 'error' ? 'danger' : 'success'} position-fixed`;
        toast.style.cssText = 'top: 20px; right: 20px; z-index: 2000; min-width: 250px;';
        toast.textContent = message;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
}

// Initialize reader when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new OptimizedReader();
});

// Handle translation popup actions
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('add-to-learning')?.addEventListener('click', async () => {
        const popup = document.getElementById('translation-popup');
        const word = popup?.dataset.currentWord;
        
        if (word) {
            try {
                const response = await fetch('/api/add-word-to-learning', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || ''
                    },
                    body: JSON.stringify({ word: word })
                });

                if (response.ok) {
                    popup.style.display = 'none';
                    // Show success message
                    const toast = document.createElement('div');
                    toast.className = 'alert alert-success position-fixed';
                    toast.style.cssText = 'top: 20px; right: 20px; z-index: 2000; min-width: 250px;';
                    toast.textContent = `"${word}" added to learning list!`;
                    document.body.appendChild(toast);
                    setTimeout(() => toast.remove(), 3000);
                }
            } catch (error) {
                console.error('Add word error:', error);
            }
        }
    });

    document.getElementById('close-popup')?.addEventListener('click', () => {
        document.getElementById('translation-popup').style.display = 'none';
    });
});