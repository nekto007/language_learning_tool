# Header/Footer Inventory — Public vs Cabinet Layouts

Снимок состояния на 2026-05-31 для рефактора `public_base.html` / `base.html`. Подготовка к Task 2–6 плана `2026-05-31-header-footer-refresh.md`.

## 1. Публичные endpoint'ы (доступны анонимам, рендерятся через `public_base.html` после Task 5)

| Раздел | Endpoint | URL | Шаблон | Доступ |
| --- | --- | --- | --- | --- |
| Лендинг | `landing.index` | `/` | `landing/index.html` | anon + auth |
| Каталог курсов | `courses.catalog` | `/learn/` | `curriculum/public_catalog.html` | anon + auth |
| CEFR-уровень | `courses.level_detail` | `/learn/<level>` | `curriculum/public_level.html` | anon + auth |
| Grammar Lab | `grammar_lab.index` | `/grammar/` | `grammar_lab/index.html` | anon + auth |
| Темы грамматики | `grammar_lab.topics` | `/grammar/topics/` | `grammar_lab/topics.html` | anon + auth |
| Тема грамматики | `grammar_lab.topic_detail` | `/grammar/<slug>/` | `grammar_lab/topic_detail.html` | anon + auth |
| Публичный словарь | `words.public_dictionary` | `/dictionary/` | `words/public_dictionary.html` | anon + auth |
| Слово | `words.public_word` | `/word/<id>/` | `words/public_word.html` | anon + auth |
| Сравнение слов | `words.public_contrast` | `/word/.../vs/...` | `words/public_contrast.html` | anon + auth |
| Публичный профиль | `auth.public_profile` | `/u/<username>/` | `auth/public_profile.html` | anon + auth (SEO) |
| Публичный streak | `achievements.public_streak` | `/streak/<username>/` | `achievements/public_streak.html` | anon + auth (SEO) |
| Политика | `legal.privacy` | `/privacy` | `legal/privacy.html` | anon + auth |
| Вход | `auth.login` | `/login` | `auth/login.html` | anon only |
| Регистрация | `auth.register` | `/register` | `auth/register.html` | anon only |
| Сброс пароля (request) | `auth.reset_request` | `/reset` | `auth/reset_request.html` | anon only |
| Сброс пароля (set) | `auth.reset_password` | `/reset/<token>` | `auth/reset_password.html` | anon only |

## 2. Кабинетные разделы (только auth, остаются на `base.html`)

Группа «Слова» (dropdown):
- `words.word_list` — `/words/`
- `study.collections` — `/study/collections/`
- `study.topics` — `/study/topics/`

Группа «Карточки»: `study.index` — `/study/`

Группа «Курсы» (dropdown):
- `courses.catalog` (внутренний линк) — `/learn/`
- `book_courses.list_book_courses` (только auth) — `/book-courses`
- быстрый «Продолжить» на текущий lesson/course

Группа «Книги» (dropdown):
- `books.book_list` — `/books/`
- быстрый «Продолжить чтение» (последняя глава)

Группа «Грамматика» (dropdown):
- `grammar_lab.index`
- `grammar_lab.topics`
- `grammar_lab.practice` (auth)
- `grammar_lab.stats` (auth)

User-group (правая часть navbar):
- notification bell (`/api/notifications/...`)
- quick-actions dropdown (Начать повторение, Продолжить урок, Практика грамматики)
- user dropdown: Админ-панель (если admin), Статистика, Профиль, Приглашения, Настройки, Модули, Выход

Дополнительные кабинетные виджеты (внутри `base.html`):
- XP-bar (под navbar)
- daily plan progress (`components/_daily_plan_progress.html`)
- feedback widget (`components/_feedback_widget.html`)
- mobile bottom-nav (Главная, Курсы, Карточки, Грамматика, Ещё → Книги/Слова/Статистика/Настройки)
- celebrations/level-up модал
- CSRF auto-refresh

## 3. Сломанные ссылки в текущем `public_base.html`

| Пункт меню | Endpoint | Проблема | Решение |
| --- | --- | --- | --- |
| «Книги» | `book_courses.list_book_courses` | `@login_required` → анон редиректится на `/login?next=/book-courses` | Удалить из публичного header'а в Task 3 (нет публичного эквивалента). При появлении публичного preview позже — вернуть. |

Других битых ссылок не обнаружено.

## 4. Решения для нового публичного header'а (Task 3)

Группы:
1. Контентная навигация (по `request.endpoint` для active-state):
   - Курсы → `courses.catalog`
   - Грамматика → `grammar_lab.index`
   - Словарь → `words.public_dictionary`
2. CTA (правый край):
   - anon: «Вход» (`auth.login`) + «Регистрация» (`auth.register`, primary)
   - auth: «Открыть кабинет» (`words.dashboard`, primary)

Adaptive:
- desktop (≥1024px): brand + горизонтальное меню + CTA
- tablet (700–1023px) / mobile (<700px): brand + hamburger (`<details><summary>`) с теми же пунктами, складывается в колонку
- sticky header с лёгкой shadow при скролле (CSS-only `position: sticky`)
- A11Y: `aria-expanded` на hamburger, `aria-current="page"` на активной ссылке, role="navigation" на `<nav>`

## 5. Структура нового публичного footer'а (Task 4)

Desktop (≥700px) — 3 колонки grid:

| Колонка 1: Продукт | Колонка 2: Полезное | Колонка 3: Юридическое |
| --- | --- | --- |
| Курсы (`courses.catalog`) | `site_settings.support_email` (если задан, `mailto:`) | Политика конфиденциальности (`legal.privacy`) |
| Грамматика (`grammar_lab.index`) | `site_settings.support_phone` (если задан, plain text) | (зарезервировано под доп. легал-страницы — не добавляем заглушек) |
| Словарь (`words.public_dictionary`) | | |

Bottom-row (под колонками):
- brand «LLT English» + краткий tagline
- copyright «© <current_year>» (динамически через `{{ now().year }}` / `datetime.utcnow().year`)

Mobile (<700px): колонки складываются вертикально, выравнивание по центру.

## 6. Кабинетные разделы — статус для Task 6

Состав разделов в navbar остаётся прежним (Слова / Карточки / Курсы / Грамматика / Книги — каждый под `has_module`). Изменения:
- визуальная унификация с design-system.css (никаких inline-стилей в шапке/футере)
- tablet 768–1023: текстовые лейблы сокращаются до иконок (`d-none d-md-inline` обёртки)
- active-state унифицируется через `request.endpoint` matching (уже есть, проверить пробелы)
- bottom-nav: пересмотреть, чтобы все основные разделы навигации присутствовали (Главная, Курсы, Карточки, Грамматика, Ещё[Книги/Слова/Статистика/Настройки]) — состав сохраняется

Новых пунктов в кабинетной шапке не добавляем (`achievements`, `race` остаются доступны через user dropdown / dashboard виджеты, как сейчас).
