/* Linear daily plan: book-select modal wiring.
 *
 * - Opens #book-select-modal when a slot link points at it
 *   (href="#book-select-modal" or data-linear-action="select-book").
 * - Loads /api/books/catalog on first open and renders book cards.
 * - The pilot offers a read-only excerpt and an explicit select action.
 * - On book selection, POSTs to /api/books/select and closes the modal.
 *   On success, refreshes the dashboard so the reading slot reflects
 *   the new selection (cheaper than partial re-rendering for now).
 */
(function () {
    'use strict';

    // UI-029: see components/_lesson_i18n.html. Russian stays as the fallback so
    // today's single-locale rendering is unchanged.
    function _t(key, fallback) {
        var dict = window.I18N || {};
        return (typeof dict[key] === 'string' && dict[key]) ? dict[key] : fallback;
    }

    var MODAL_ID = 'book-select-modal';
    var STATUS_ID = 'book-select-modal-status';
    var LIST_ID = 'book-select-modal-list';
    var modalTrigger = null;
    var excerptTrigger = null;
    var excerptRequest = null;
    var catalogScroll = 0;

    function $(id) { return document.getElementById(id); }

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function openModal(trigger) {
        var modal = $(MODAL_ID);
        if (!modal) return;
        modalTrigger = trigger;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('linear-modal-open');
        modal.querySelector('.linear-modal__close').focus();
        loadCatalog();
    }

    function closeModal() {
        var modal = $(MODAL_ID);
        if (!modal) return;
        closeExcerpt(false);
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('linear-modal-open');
        if (modalTrigger) modalTrigger.focus();
        modalTrigger = null;
    }

    function closeExcerpt(restoreFocus) {
        var excerpt = $('book-plan-excerpt');
        if (!excerpt || excerpt.hidden) return;
        var trigger = excerptTrigger;
        excerptTrigger = null;
        if (excerptRequest) excerptRequest.abort();
        excerptRequest = null;
        excerpt.hidden = true;
        $('book-select-catalog').hidden = false;
        $('book-select-modal-body').scrollTop = catalogScroll;
        if (restoreFocus && trigger) trigger.focus({preventScroll: true});
    }

    async function openExcerpt(book, trigger) {
        var body = $('book-select-modal-body');
        var heading = $('book-plan-excerpt-title');
        var status = $('book-plan-excerpt-status');
        var content = $('book-plan-excerpt-body');
        var controller = new AbortController();
        excerptRequest = controller;
        excerptTrigger = trigger;
        catalogScroll = body.scrollTop;
        $('book-select-catalog').hidden = true;
        $('book-plan-excerpt').hidden = false;
        heading.textContent = book.title;
        content.hidden = true;
        status.textContent = _t('plan_excerpt_loading', 'Загрузка отрывка…');
        body.scrollTop = 0;
        heading.focus({preventScroll: true});
        try {
            var response = await fetch(book.plan_excerpt_url, {
                credentials: 'same-origin', headers: {'Accept': 'application/json'}, signal: controller.signal
            });
            if (!response.ok) throw new Error('excerpt_unavailable');
            var data = await response.json();
            if (controller.signal.aborted) return;
            var meta = [
                _t('plan_excerpt_level', 'Уровень {level}').replace('{level}', data.level),
                _t('plan_excerpt_duration', '≈ {minutes} мин чтения').replace('{minutes}', data.minutes)
            ];
            if (data.chapter_title) meta.unshift(data.chapter_title);
            $('book-plan-excerpt-meta').textContent = meta.join(' · ');
            var text = $('book-plan-excerpt-text');
            text.replaceChildren();
            data.paragraphs.forEach(function (value) {
                var paragraph = document.createElement('p');
                paragraph.textContent = value;
                text.appendChild(paragraph);
            });
            status.textContent = '';
            content.hidden = false;
        } catch (_) {
            if (!controller.signal.aborted) {
                status.textContent = _t('plan_excerpt_unavailable', 'Отрывок недоступен. Вернитесь к выбору книги.');
            }
        }
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
            setStatus(_t('no_books_for_level', 'Книг под ваш уровень пока нет.'));
            return;
        }
        setStatus('');
        books.forEach(function (book) {
            var li = document.createElement('li');
            var card = document.createElement('div');
            card.className = 'linear-book-card';
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
            if (book.plan_excerpt_url) {
                card.classList.add('linear-book-card--excerpt');
                var actions = document.createElement('div');
                actions.className = 'plan-excerpt__actions';
                var read = document.createElement('button');
                read.type = 'button';
                read.className = 'btn btn-sm btn-outline-primary';
                read.textContent = _t('plan_excerpt_read', 'Читать отрывок');
                read.addEventListener('click', function () { openExcerpt(book, read); });
                var choose = document.createElement('button');
                choose.type = 'button';
                choose.className = 'btn btn-sm btn-primary';
                choose.textContent = _t('plan_excerpt_choose', 'Выбрать в план');
                choose.addEventListener('click', function () { selectBook(book.id); });
                actions.append(read, choose);
                body.appendChild(actions);
            } else {
                card.setAttribute('role', 'button');
                card.setAttribute('tabindex', '0');
                card.addEventListener('click', function () { selectBook(book.id); });
                card.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        selectBook(book.id);
                    }
                });
            }
            li.appendChild(card);
            list.appendChild(li);
        });
    }

    function loadCatalog() {
        setStatus(_t('catalog_loading', 'Загрузка каталога…'));
        var list = $(LIST_ID);
        if (list) list.innerHTML = '';
        fetch('/api/books/catalog?view=plan_picker', {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function (resp) {
            if (!resp.ok) throw new Error('catalog_failed');
            return resp.json();
        }).then(function (data) {
            renderBooks(data && data.books);
        }).catch(function () {
            setStatus(_t('catalog_failed', 'Не удалось загрузить каталог. Попробуйте обновить страницу.'));
        });
    }

    function selectBook(bookId) {
        setStatus(_t('choice_saving', 'Сохраняем выбор…'));
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
            setStatus(_t('choice_failed', 'Не удалось сохранить выбор. Попробуйте ещё раз.'));
        });
    }

    function isLinearReadingTrigger(target) {
        if (!target) return false;
        if (target.matches && target.matches('[data-linear-action="select-book"]')) return true;
        var anchor = target.closest && target.closest('a[href="#book-select-modal"]');
        return !!anchor;
    }

    /* Locked-slot click guard.
     *
     * In the infinite chain only the first incomplete slot is current; every
     * later slot renders with `data-slot-state="locked"` and shows a lock
     * badge instead of an action link. If a user manages to click anywhere
     * inside a locked slot, swallow the click and surface a small toast so
     * they understand why nothing happened.
     */
    var TOAST_ID = 'linear-locked-toast';
    var _toastTimer = null;

    function _showLockedToast(message) {
        var toast = document.getElementById(TOAST_ID);
        if (!toast) {
            toast = document.createElement('div');
            toast.id = TOAST_ID;
            toast.className = 'linear-locked-toast';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('linear-locked-toast--visible');
        if (_toastTimer) clearTimeout(_toastTimer);
        _toastTimer = setTimeout(function () {
            toast.classList.remove('linear-locked-toast--visible');
        }, 2400);
    }

    function _findLockedSlot(target) {
        if (!target || !target.closest) return null;
        return target.closest('[data-slot-state="locked"]');
    }

    function _findSkipSlotButton(target) {
        if (!target || !target.closest) return null;
        return target.closest('[data-skip-slot-button="true"]');
    }

    function _skipSlot(button) {
        var slotKind = button.getAttribute('data-skip-kind') || '';
        if (!slotKind) {
            _showLockedToast(_t('step_unknown', 'Не удалось определить шаг'));
            return;
        }
        button.disabled = true;
        fetch('/api/daily-plan/events', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                event_type: 'slot_skipped',
                step_kind: slotKind,
                reason_text: button.getAttribute('data-skip-reason') || 'not_today'
            })
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.json().catch(function () { return {}; }).then(function (data) {
                    throw new Error(data.message || _t('skip_step_failed', 'Не удалось пропустить шаг'));
                });
            }
            return resp.json();
        }).then(function () {
            window.location.reload();
        }).catch(function (err) {
            button.disabled = false;
            _showLockedToast(err && err.message ? err.message : _t('skip_step_failed', 'Не удалось пропустить шаг'));
        });
    }

    document.addEventListener('click', function (event) {
        if (event.target.closest && event.target.closest('[data-book-excerpt-back]')) {
            closeExcerpt(true);
            return;
        }
        var closeTarget = event.target.closest && event.target.closest('[data-linear-close="' + MODAL_ID + '"]');
        if (closeTarget) {
            event.preventDefault();
            closeModal();
            return;
        }
        var skipSlot = _findSkipSlotButton(event.target);
        if (skipSlot) {
            event.preventDefault();
            event.stopPropagation();
            _skipSlot(skipSlot);
            return;
        }
        var lockedSlot = _findLockedSlot(event.target);
        if (lockedSlot) {
            event.preventDefault();
            event.stopPropagation();
            _showLockedToast(_t('finish_previous_first', 'Сначала завершите предыдущее задание'));
            return;
        }
        if (isLinearReadingTrigger(event.target)) {
            event.preventDefault();
            openModal(event.target.closest('a[href="#book-select-modal"], [data-linear-action="select-book"]'));
        }
    });

    document.addEventListener('keydown', function (event) {
        var modal = $(MODAL_ID);
        if (!modal || modal.hidden) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            if (excerptTrigger) closeExcerpt(true);
            else closeModal();
        } else if (event.key === 'Tab') {
            var controls = Array.from(modal.querySelectorAll('a[href], button:not([disabled]), [tabindex="0"]'))
                .filter(function (node) { return node.getClientRects().length; });
            var first = controls[0];
            var last = controls[controls.length - 1];
            if (document.activeElement === $('book-plan-excerpt-title')) {
                event.preventDefault();
                (event.shiftKey ? first : last).focus();
            } else if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });

    /* Day-secured banner integration.
     *
     * - On dashboards rendered with the day-secured banner, the linear-plan
     *   context must be cleared: the user has finished every baseline slot
     *   for today, so any stale sessionStorage marker should not leak into
     *   the next lesson they open from the continuation CTA.
     * - The "На сегодня хватит" CTA dismisses the banner in-place without
     *   reloading the page. It also strips the `?day_secured=1` query-param
     *   from the URL so a subsequent refresh does not re-render it.
     */
    function _getBannerEl() {
        return document.querySelector('[data-linear-day-secured-banner="true"]');
    }

    function _clearLinearContextIfAvailable() {
        if (window.linearPlanContext && typeof window.linearPlanContext.clear === 'function') {
            window.linearPlanContext.clear();
        }
    }

    function _stripDaySecuredQueryParam() {
        try {
            var url = new URL(window.location.href);
            if (!url.searchParams.has('day_secured')) return;
            url.searchParams.delete('day_secured');
            var clean = url.pathname + (url.search ? url.search : '') + (url.hash || '');
            window.history.replaceState({}, document.title, clean);
        } catch (e) {
            /* ignore */
        }
    }

    function _dismissBanner() {
        var banner = _getBannerEl();
        if (banner && banner.parentNode) {
            banner.parentNode.removeChild(banner);
        }
        _stripDaySecuredQueryParam();
    }

    function _initDaySecuredBanner() {
        if (!_getBannerEl()) return;
        _clearLinearContextIfAvailable();
    }

    document.addEventListener('click', function (event) {
        var target = event.target;
        var dismiss = target.closest && target.closest('[data-linear-action="day-secured-dismiss"]');
        if (dismiss) {
            event.preventDefault();
            _dismissBanner();
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _initDaySecuredBanner);
    } else {
        _initDaySecuredBanner();
    }

    /* Chain-growth toast.
     *
     * The slot chain only grows between page loads (the linear partial is
     * rerendered server-side). On each render we read the current chain
     * length from the slots container and compare it with the value we
     * stored in sessionStorage on the previous render. If the chain grew,
     * surface a short toast so the user notices the new task that was
     * appended after they finished the previous one.
     */
    var CHAIN_LENGTH_STORAGE_KEY_PREFIX = 'linearPlanChainLength:';

    function _getChainStorageKey() {
        var el = document.querySelector('[data-linear-slots="true"]');
        var userId = (el && el.getAttribute('data-linear-user-id')) || 'anon';
        // Scope by the user's profile-timezone date computed server-side.
        // Falling back to the browser clock would re-introduce cross-day
        // toast misfires when the browser's tz differs from the profile tz.
        var dateKey = (el && el.getAttribute('data-linear-plan-date')) || '';
        if (!dateKey) {
            var d = new Date();
            dateKey = d.getFullYear() + '-' +
                String(d.getMonth() + 1).padStart(2, '0') + '-' +
                String(d.getDate()).padStart(2, '0');
        }
        return CHAIN_LENGTH_STORAGE_KEY_PREFIX + userId + ':' + dateKey;
    }

    function _getChainLength() {
        var el = document.querySelector('[data-linear-slots="true"]');
        if (!el) return null;
        var raw = el.getAttribute('data-linear-chain-length');
        var n = parseInt(raw, 10);
        return isNaN(n) ? null : n;
    }

    function _showChainGrowthToast(delta) {
        var toast = document.getElementById('linear-chain-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'linear-chain-toast';
            toast.className = 'linear-plan__chain-toast';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            document.body.appendChild(toast);
        }
        var prefix = delta === 1
            ? _t('task_added_one', '+1 задание добавлено')
            : '+' + delta + ' ' + _t('tasks_added_many', 'заданий добавлено');
        toast.textContent = prefix;
        toast.classList.add('linear-plan__chain-toast--visible');
        setTimeout(function () {
            toast.classList.remove('linear-plan__chain-toast--visible');
        }, 2400);
    }

    function _initChainGrowthDetector() {
        var current = _getChainLength();
        if (current === null) return;
        var key = _getChainStorageKey();
        var stored = null;
        try {
            var raw = sessionStorage.getItem(key);
            stored = raw === null ? null : parseInt(raw, 10);
            if (isNaN(stored)) stored = null;
        } catch (e) {
            stored = null;
        }
        if (stored !== null && current > stored) {
            _showChainGrowthToast(current - stored);
        }
        try {
            sessionStorage.setItem(key, String(current));
        } catch (e) {
            /* ignore */
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _initChainGrowthDetector);
    } else {
        _initChainGrowthDetector();
    }
})();
