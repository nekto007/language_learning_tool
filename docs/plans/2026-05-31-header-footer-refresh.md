# Переосмысление шапки и футера: публичная vs кабинетная навигация

## Overview

Чётко разделить две системы layout'ов: тонкий `public_base.html` — для всех публичных/SEO-страниц (лендинг, `courses.catalog/level`, grammar_lab публичные, words публичные, book_courses публичный обзор, legal, auth-формы, public_profile, public_streak); полноценный `base.html` — только для авторизованного кабинета (dashboard, study, кабинетные книги, кабинетные курсы, профиль, настройки, achievements, admin). Параллельно — переосмыслить дизайн обеих шапок и футеров с актуализацией ссылок, нормальной мобильной/планшетной адаптацией (hamburger, sticky bottom-nav для кабинета), полным набором разделов в обоих layout'ах, и наведением порядка во footer-структуре (колонки с ссылками, контакты, легал, соцссылки если есть в SiteSettings).

## Context

- Текущая шапка/футер кабинета: `app/templates/base.html` (Bootstrap navbar + footer + mobile bottom-nav).
- Текущая публичная шапка/футер: `app/templates/public_base.html` (минималистичный inline-CSS layout).
- Текущая раздача:
  - public_base.html: words/public_word, words/public_contrast.
  - Условные (`extends 'base.html' if auth else 'public_base.html'`): landing/index, curriculum/public_catalog, curriculum/public_level, grammar_lab/index, grammar_lab/topics, grammar_lab/topic_detail, words/public_dictionary.
  - base.html (но для анонимных гостей по сути публичные): legal/privacy, auth/login, auth/register, auth/reset_request, auth/reset_password, auth/public_profile, achievements/public_streak, curriculum/book_courses/list, grammar_lab/practice (`login_required` → ок), books/list (`login_required` → ок).
- Сломанная ссылка: public_base.html сейчас ведёт «Книги» на `book_courses.list_book_courses`, который `@login_required` — анонимы получают редирект на login. Нужен публичный обзор книжных курсов или удаление пункта.
- Сторонние компоненты base.html, которые кабинетная шапка обязана хостить (а публичная — нет): XP-бар, daily plan progress, notification bell, quick actions, user dropdown, feedback widget, mobile bottom-nav, celebrations/level-up модал, CSRF auto-refresh.
- Существующие данные в footer: `site_settings.support_email`, `site_settings.support_phone` (используется в base.html), `site_settings.site_title`/`site_description`.
- design-system.css уже хостит классы для kabinet-навигации (`.bottom-nav`, `.xp-bar`, `.dash-*`). Публичные стили сейчас живут inline в `public_base.html` — выносим в design-system.css секцию `/* === Public layout === */` для консистентности.
- CSP-nonce обязателен на все inline `<script>` (`g.csp_nonce`).
- Файлы: `app/templates/base.html`, `app/templates/public_base.html`, `app/templates/landing/index.html`, `app/templates/curriculum/public_catalog.html`, `app/templates/curriculum/public_level.html`, `app/templates/grammar_lab/{index,topics,topic_detail}.html`, `app/templates/words/{public_word,public_contrast,public_dictionary}.html`, `app/templates/legal/privacy.html`, `app/templates/auth/{login,register,reset_request,reset_password,public_profile}.html`, `app/templates/achievements/public_streak.html`, `app/static/css/design-system.css`, plus smoke-тесты в `tests/`.

## Development Approach

- Testing approach: Regular (code first, then tests) — UI-рефакторинг шаблонов, тесты — smoke (рендер страниц + статус 200 + наличие ключевых элементов в HTML).
- Каждый Task завершается полностью (включая тесты и `pytest -m smoke`) перед стартом следующего.
- Никаких BC-shim'ов — публичные SEO-страницы сразу переключаются на public_base.html для всех (auth/anon), кабинетные — остаются на base.html.
- Inline-стили public_base.html переезжают в design-system.css (один источник, легче поддерживать).
- Делаем визуально консистентные header/footer (одна типографика, palette, spacing), но с разной плотностью (публичный — легче, кабинетный — функциональнее).
- CRITICAL: каждая Task включает новые/обновлённые smoke-тесты.
- CRITICAL: все тесты должны проходить (полный `pytest`) до начала следующего Task.

## Implementation Steps

### Task 1: Аудит и инвентаризация ссылок/разделов

**Files:**
- Read-only: все blueprint `__init__`/routes для составления полного списка публичных и кабинетных endpoint'ов (landing, courses, grammar_lab, words public, book_courses, legal, auth, study, curriculum, books, achievements, admin, profile, modules, race).
- Create: `docs/design/header-footer-inventory.md` (короткий чеклист: какие пункты в шапке/футере публичного layout'а, какие — в кабинетном, какие исчезли как сломанные).

- [x] Собрать список публичных endpoint'ов (anon-доступные SEO-страницы) с canonical-путями.
- [x] Собрать список кабинетных разделов (что ведёт в навбаре авторизованного юзера).
- [x] Зафиксировать сломанные ссылки (book_courses anon) и решения (удалить из public nav, либо добавить публичный preview позже — фиксируем «удалить из public nav в Task 3» как scope-решение).
- [x] Зафиксировать структуру нового footer: 3 колонки на desktop (Продукт / Контент / Юридическое+Контакты) + 1 колонка на mobile.
- [x] Записать соответствие cabinet-nav секций: Слова, Карточки, Курсы, Грамматика, Книги, + user/quick-actions/notif/XP — без изменений по составу, только визуальный рефакторинг.
- [x] Smoke-тест: `pytest -m smoke` (baseline, должен проходить).

### Task 2: Вынести публичные стили из public_base.html в design-system.css

**Files:**
- Modify: `app/static/css/design-system.css` (добавить новую секцию `/* === Public layout (header/footer/nav) === */`).
- Modify: `app/templates/public_base.html` (удалить `<style>` блок, подключить design-system.css; сохранить кастомный CSS-нончу там, где CSP требует).

- [x] Перенести существующие `.public-*` классы в design-system.css.
- [x] Подключить design-system.css в `<head>` public_base.html (с тем же `?v=` версионированием).
- [x] Удалить inline `<style>` блок из public_base.html.
- [x] Проверить визуально через `flask run` (test_client), что текущие public-страницы рендерятся без регрессий.
- [x] Smoke-test: добавить/обновить тест `tests/smoke/test_public_layout.py::test_public_pages_render` — рендерит landing, courses.catalog, grammar_lab.index, words.public_dictionary анонимом, проверяет 200 + содержит `class="public-header"`.
- [x] `pytest -m smoke` — обязан проходить.

### Task 3: Новый адаптивный публичный header (с hamburger, новой структурой) + актуализированные ссылки

**Files:**
- Modify: `app/templates/public_base.html` (header markup + поведение).
- Modify: `app/static/css/design-system.css` (responsive rules для public header: desktop ≥1024, tablet 700–1023, mobile <700; hamburger toggle через details/summary без JS либо короткий CSP-safe inline JS с nonce).

- [x] Разделить навигацию на две группы: контентная (Курсы, Грамматика, Словарь) и CTA (Вход / Регистрация для anon; «Открыть кабинет» для auth).
- [x] Убрать сломанную ссылку «Книги» (book_courses public требует login) — заменить на нет-линка либо оставить только при наличии будущего public/list (сейчас удаляем).
- [x] Добавить hamburger-меню для tablet/mobile (<1024px): кнопка в правом верхнем углу, раскрывающаяся панель с теми же ссылками. Реализация — `<details><summary>` (zero-JS, accessible) или короткий nonce-скрипт-toggle, если нужна анимация.
- [x] Sticky-header (`position: sticky; top: 0; z-index`) с тонкой shadow при скролле (CSS-only через `position: sticky`).
- [x] Active-state подсветка текущего раздела (по `request.endpoint`).
- [x] A11Y: `aria-expanded` на hamburger-кнопке, `aria-current` на активной ссылке, `role="navigation"` уже есть на nav.
- [x] Тесты: расширить `test_public_layout.py` — проверить присутствие hamburger-кнопки, проверить, что «Книги» не ведёт на /book-courses (или вообще отсутствует), проверить active-class на текущем endpoint.
- [x] `pytest -m smoke` — обязан проходить.

### Task 4: Новый адаптивный публичный footer

**Files:**
- Modify: `app/templates/public_base.html` (footer markup).
- Modify: `app/static/css/design-system.css` (классы `.public-footer__grid`, `.public-footer__col`, mobile-stack).

- [x] Реструктурировать footer как 3-колоночный grid: «Продукт» (Курсы, Грамматика, Словарь), «Полезное» (Контакты/email — из site_settings, Помощь — пока нет, скрываем), «Юридическое» (Политика конфиденциальности; поддержка дополнительных легал-страниц — структура готова на будущее, но не добавляем заглушек).
- [x] Внизу — copyright + brand (год динамический через `now().year`).
- [x] Mobile (<700): стек в одну колонку, центрирование.
- [x] Использовать `site_settings.support_email`, `site_settings.support_phone` при наличии; ничего не показывать, если поле пустое.
- [x] Тесты: `test_public_layout.py::test_public_footer_has_legal_link` — проверяет наличие ссылки на `/privacy` и copyright в render'е landing-страницы.
- [x] `pytest -m smoke`.

### Task 5: Миграция SEO/публичных страниц на public_base.html

**Files:**
- Modify: `app/templates/legal/privacy.html` (extends public_base.html).
- Modify: `app/templates/auth/login.html`, `auth/register.html`, `auth/reset_request.html`, `auth/reset_password.html` (extends public_base.html — анонимные потоки).
- Modify: `app/templates/auth/public_profile.html`, `app/templates/achievements/public_streak.html` (extends public_base.html — SEO, открыты для anon).
- Modify: `app/templates/curriculum/public_catalog.html`, `app/templates/curriculum/public_level.html`, `app/templates/grammar_lab/index.html`, `app/templates/grammar_lab/topics.html`, `app/templates/grammar_lab/topic_detail.html`, `app/templates/words/public_dictionary.html`, `app/templates/landing/index.html` (убрать `if current_user.is_authenticated else` — всегда `extends 'public_base.html'`; в public_base header пункт «Открыть кабинет» для авторизованных уже есть).

- [x] Для каждого шаблона: поправить extends, проверить, что используются только блоки `content`/`title`/`meta_description`/`og_*`/`styles`/`extra_css`/`extra_js`/`scripts`/`canonical`/`robots`/`head_extra`/`body_class` (все объявлены в public_base.html).
- [x] Если шаблон использовал блок, отсутствующий в public_base.html (например, `og_image`), убедиться что он есть; добавить недостающие в public_base.html.
- [x] Удалить из этих шаблонов любые предположения о наличии `xp-bar`, `bottom-nav`, `feedback-widget` (их в public_base.html нет — должно быть и не было).
- [x] Smoke-тесты: расширить `test_public_layout.py` — рендер каждого мигрированного endpoint'а анонимом, проверка `public-header` присутствует, `navbar-expand-lg` (Bootstrap) отсутствует.
- [x] `pytest` полный — обязан проходить.

### Task 6: Переосмысление кабинетной шапки (base.html) — адаптивность, актуализация

**Files:**
- Modify: `app/templates/base.html` (markup шапки: реорганизация секций, улучшение dropdown'ов на touch, нормальный mobile-collapse).
- Modify: `app/static/css/design-system.css` (классы `.cabinet-nav`, медиа-запросы для tablet 768–1023 — гибрид: компактные иконки вместо текста; mobile <768 — Bootstrap collapse уже работает, доработать стилизацию).

- [x] Сохранить структуру разделов (Слова, Карточки, Курсы, Грамматика, Книги — с условием has_module), но проверить, что все актуальные endpoints представлены: добавить недостающие пункты (например, Achievements, Race — если активны как модули; либо оставить только в user dropdown).
- [x] Quick-actions, notification bell, user dropdown — оставить, но навести порядок (иконки + tooltip-aria, не отсутствует).
- [x] Tablet (768–1023): сократить текстовые лейблы до иконок (CSS-only через `.d-none .d-md-inline`).
- [x] Mobile (<768): Bootstrap navbar collapse работает; добавить корректный фокус-стейт для hamburger.
- [x] Active-state для всех разделов (унифицировать через `request.endpoint` matching).
- [x] XP-bar — сохранить, но проверить, что не ломается на узких экранах (текущие `xp-bar__text-short`/`xp-bar__text-full` — оставить).
- [x] bottom-nav (mobile-only) — добавить недостающие разделы, согласовать с верхней навигацией; убедиться, что dropdown «Ещё» не перекрывает контент.
- [x] Footer кабинета (внутри base.html) — синхронизировать визуально с публичным footer'ом, оставить более компактным.
- [x] Тесты: новый `tests/smoke/test_cabinet_layout.py::test_cabinet_nav_renders_for_auth_user` — авторизованный юзер видит navbar-expand-lg и bottom-nav на dashboard.
- [x] `pytest -m smoke`.

### Task 7: Финальная проверка приёмочных критериев

- [ ] Запустить полный `pytest` — все тесты зелёные.
- [ ] Запустить smoke-набор отдельно: `pytest -m smoke` (<30c).
- [ ] Проверить через `python -c "from app import create_app; create_app().test_client().get('/').status_code"` для ключевых публичных URL: /, /learn/, /grammar/, /dictionary/, /privacy, /login, /register.
- [ ] Проверить, что в публичных страницах нет ссылок на login-required endpoints с anon-перенаправлением (особенно book_courses).
- [ ] Проверить CSP — все inline-скрипты в обоих layout'ах имеют `nonce="{{ csp_nonce }}"`.
- [ ] Визуально протестировать в браузере: desktop (1440), tablet (768), mobile (375) — landing, courses.catalog, dashboard (auth), study.index (auth).

### Task 8: Обновить документацию

- [ ] Обновить CLAUDE.md в секции «Project Overview» — зафиксировать новое правило: «SEO/публичные страницы → public_base.html; кабинетные → base.html; никаких conditional extends».
- [ ] Добавить в CLAUDE.md описание правил адаптации (breakpoints: ≥1024 desktop, 768–1023 tablet, <768 mobile) и где живут публичные стили (design-system.css секция «Public layout»).
- [ ] Решить судьбу `docs/design/header-footer-inventory.md` из Task 1 — оставить как историческую справку либо удалить.
