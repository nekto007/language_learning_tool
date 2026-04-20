/* Linear daily plan: book-select modal wiring.
 *
 * - Opens #book-select-modal when a slot link points at it
 *   (href="#book-select-modal" or data-linear-action="select-book").
 * - Loads /api/books/catalog on first open and renders book cards.
 * - On book click, POSTs to /api/books/select and closes the modal.
 *   On success, refreshes the dashboard so the reading slot reflects
 *   the new selection (cheaper than partial re-rendering for now).
 */
(function () {
    'use strict';

    var MODAL_ID = 'book-select-modal';
    var STATUS_ID = 'book-select-modal-status';
    var LIST_ID = 'book-select-modal-list';

    function $(id) { return document.getElementById(id); }

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function openModal() {
        var modal = $(MODAL_ID);
        if (!modal) return;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('linear-modal-open');
        loadCatalog();
    }

    function closeModal() {
        var modal = $(MODAL_ID);
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('linear-modal-open');
    }

    function setStatus(text) {
        var el = $(STATUS_ID);
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = '';
        } else {
            el.hidden = false;
            el.textContent = text;
        }
    }

    function renderBooks(books) {
        var list = $(LIST_ID);
        if (!list) return;
        list.innerHTML = '';
        if (!books || !books.length) {
            setStatus('Книг под ваш уровень пока нет.');
            return;
        }
        setStatus('');
        books.forEach(function (book) {
            var li = document.createElement('li');
            var card = document.createElement('div');
            card.className = 'linear-book-card';
            card.setAttribute('role', 'button');
            card.setAttribute('tabindex', '0');
            card.setAttribute('data-book-id', String(book.id));

            if (book.cover_image) {
                var img = document.createElement('img');
                img.className = 'linear-book-card__cover';
                img.alt = '';
                img.src = book.cover_image;
                card.appendChild(img);
            }

            var body = document.createElement('div');
            body.className = 'linear-book-card__body';

            var title = document.createElement('p');
            title.className = 'linear-book-card__title';
            title.textContent = book.title || '';
            body.appendChild(title);

            var meta = document.createElement('p');
            meta.className = 'linear-book-card__meta';
            if (book.level) {
                var level = document.createElement('span');
                level.className = 'linear-book-card__level';
                level.textContent = book.level;
                meta.appendChild(level);
            }
            meta.appendChild(document.createTextNode(book.author || ''));
            body.appendChild(meta);

            if (book.summary) {
                var summary = document.createElement('p');
                summary.className = 'linear-book-card__summary';
                summary.textContent = book.summary;
                body.appendChild(summary);
            }

            card.appendChild(body);
            card.addEventListener('click', function () { selectBook(book.id); });
            card.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectBook(book.id);
                }
            });
            li.appendChild(card);
            list.appendChild(li);
        });
    }

    function loadCatalog() {
        setStatus('Загрузка каталога…');
        var list = $(LIST_ID);
        if (list) list.innerHTML = '';
        fetch('/api/books/catalog', {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function (resp) {
            if (!resp.ok) throw new Error('catalog_failed');
            return resp.json();
        }).then(function (data) {
            renderBooks(data && data.books);
        }).catch(function () {
            setStatus('Не удалось загрузить каталог. Попробуйте обновить страницу.');
        });
    }

    function selectBook(bookId) {
        setStatus('Сохраняем выбор…');
        fetch('/api/books/select', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ book_id: bookId })
        }).then(function (resp) {
            if (!resp.ok) throw new Error('select_failed');
            return resp.json();
        }).then(function () {
            closeModal();
            window.location.reload();
        }).catch(function () {
            setStatus('Не удалось сохранить выбор. Попробуйте ещё раз.');
        });
    }

    function isLinearReadingTrigger(target) {
        if (!target) return false;
        if (target.matches && target.matches('[data-linear-action="select-book"]')) return true;
        var anchor = target.closest && target.closest('a[href="#book-select-modal"]');
        return !!anchor;
    }

    document.addEventListener('click', function (event) {
        var closeTarget = event.target.closest && event.target.closest('[data-linear-close="' + MODAL_ID + '"]');
        if (closeTarget) {
            event.preventDefault();
            closeModal();
            return;
        }
        if (isLinearReadingTrigger(event.target)) {
            event.preventDefault();
            openModal();
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        var modal = $(MODAL_ID);
        if (modal && !modal.hidden) closeModal();
    });
})();
