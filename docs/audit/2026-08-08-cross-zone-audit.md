# Сквозной аудит 4 зон — 2026-08-08

> Реестр находок сквозного аудита: **UI · Контент · Разделы · Админка**.
> План: `docs/plans/2026-08-08-cross-zone-audit-remediation.md`.
> Образцы формата: `docs/audit/2026-06-19-daily-plan-lesson-frontend-audit.md`,
> `docs/audit/2026-06-13-100-edge-cases.md`.
>
> **Принцип:** аудит не правит код (Task 1–6), ремедиация не переоткрывает аудит (Task 7–9).
> Между ними — гейт консолидации: находки дедуплицируются и перепроверяются скептиками;
> в реестр идут только **CONFIRMED**, **PLAUSIBLE** — в приложение.

**Статус:** 🟠 Task 1–2 закрыты (каркас + baseline + зона UI: **39 находок**, 0 P0 / 7 P1 / 10 P2 / 22 P3).
Зоны Контент / Разделы / Админка — не просканированы.

---

## Как собрано

Многоагентный аудит с адверсариальной верификацией. На каждую зону — фан-аут финдеров по линзам;
каждая находка перепроверяется независимым скептиком, настроенным **опровергать** (при сомнении →
refuted); подтверждение — по факту чтения кода, а не по правдоподобию. Кросс-зонная дедупликация и
второй проход верификации по P0/P1 (три скептика с разными линзами: корректность / воспроизводимость /
влияние на пользователя) — в Task 6.

### Линзы по зонам (что запускалось)

| Зона | Линзы | Task |
|---|---|---|
| **UI** | (а) доступность · (б) fetch-надёжность · (в) i18n · (г) адаптив · (д) layout split · (е) мёртвый код | 2 |
| **Контент** | прогон валидаторов · JSON↔БД drift · (а) остатки bulk-генератора · (б) непроходимые упражнения · (в) покрытие медиа/метаданных · (г) целостность прогрессии | 3 |
| **Разделы** | инвентаризация `url_map` · (а) авторизация/гейтинг · (б) контракт ошибок · (в) производительность · (г) целостность транзакций · (д) пустые состояния | 4 |
| **Админка** | инвентаризация 19 sub-blueprint'ов · (а) покрытие аудит-логом · (б) валидация ввода · (в) экспорт/загрузки · (г) пробелы операционных инструментов · (д) админ-UI | 5 |

Секция **«Покрытие и сознательные пропуски»** (ниже) фиксирует, что просканировано, а что нет —
**без молчаливых усечений**.

---

## Схема находки

`ID | Зона | Файл:строка | Severity | Симптом | Сценарий отказа | Верификация`

| Поле | Значение |
|---|---|
| **ID** | `UI-NNN` (UI) · `CNT-NNN` (Контент) · `SEC-NNN` (Разделы) · `ADM-NNN` (Админка) · `INH-NNN` (унаследовано из аудита 2026-06-19, до перепроверки) |
| **Зона** | UI / Контент / Разделы / Админка. Кросс-зонная находка живёт в зоне первопричины, места проявления перечисляются в теле |
| **Файл:строка** | реальный `path:line` на момент аудита. Строки сдвигаются после ремедиации — сверяться с git-историей |
| **Severity** | P0 / P1 / P2 / P3 (критерии ниже) |
| **Симптом** | что видит пользователь / что ломается — одним предложением |
| **Сценарий отказа** | конкретные вход/состояние → неверный результат. Не «может сломаться», а «при X получаем Y» |
| **Верификация** | CONFIRMED (скептик не смог опровергнуть, подтверждено чтением кода) / PLAUSIBLE (не опровергнуто, но и не доказано → в приложение) |

Дополнительно у каждой находки — **финальный статус ремедиации**: ✅ закрыто · 🟡 частично · ⬜ открыто.
Task 10 проверяет, что ни одна находка не осталась без вердикта.

## Критерии severity

- **P0** — сломанный пользовательский путь или утечка данных. Флоу недоступен/нефункционален без
  обходного пути; данные пользователя видны чужому; необратимая потеря данных.
- **P1** — функциональный баг с обходом. Работает неверно, но пользователь может достичь цели другим
  путём; либо баг на неглавном пути.
- **P2** — деградация UX или производительности. Флоу работает и приводит к цели, но с лишними
  шагами, задержкой, шумом или неконсистентностью.
- **P3** — косметика и технический долг. Не влияет на поведение: мёртвый код, дублирование,
  расхождение конвенций, семантический a11y-долг при работающей клавиатуре.

**Правило понижения:** при большинстве опровержений на втором проходе (Task 6) severity понижается,
а не находка удаляется — понижение фиксируется в теле находки.

---

## Сводка severity

> Финализируется в **Task 6** после кросс-зонной дедупликации и второго прохода верификации.
> Колонка «Унаследовано» после Task 2 обнулена: 10 из 13 хвостов промотированы в `UI-NNN` и учтены
> в колонке UI, 3 закрыты как опровергнутые.

| Severity | UI | Контент | Разделы | Админка | Унаследовано | Всего |
|---|---|---|---|---|---|---|
| P0 | 0 | — | — | — | 0 | 0 |
| P1 | 7 | — | — | — | 0 | 7 |
| P2 | 10 | — | — | — | 0 | 10 |
| P3 | 22 | — | — | — | 0 | 22 |
| **Всего** | **39** | — | — | — | **0** | **39** |

**Корневые темы зоны UI** (повторяющиеся первопричины, а не симптомы):

1. **Провал сети рендерится как успех.** `catch` вызывает ту же функцию отрисовки, что и ветка
   успеха, либо глотает ошибку пустым блоком. UI-003 (ложное «Результат сохранён»), UI-011, UI-012,
   UI-018 («возможно, применилось»), UI-019. Конвенция `resp.ok` закрыта в аудите 2026-06-19 только
   для курсовых уроков — book-course уроки и виджеты остались вне её.
2. **Немигрированный легаси book-course.** Курсовой спайн отремонтирован прошлыми аудитами,
   `curriculum/book_courses/**` — нет: UI-003 и UI-007 это один и тот же необойдённый пласт.
3. **Шаблон/ассет ссылается на несуществующее и падает в 500.** UI-001 (`change_password.html`),
   UI-026 (`books/add.html`), UI-002 (блок `extra_js`, которого нет у родителя). Ни один не ловится
   тестами — все три это `TemplateNotFound`/тихий выброс блока на реальном пользовательском пути.
4. **Двойное состояние на одном DOM.** Два набора чекбоксов (UI-004), два слоя слушателей
   (UI-005), два механизма завершения на одних якорях (UI-009), двойной отступ от план-бара (UI-013).
5. **a11y-долг сосредоточен в модалках и результатах.** Никакого focus-management: UI-010, UI-015,
   UI-016, UI-020, UI-021 — один и тот же пропуск «показать/скрыть без переноса фокуса».
6. **Мёртвый груз накопился слоями.** UI-031/032/033/034/035/036/037/038/039 — 9 находок; корень
   один: удаления делались наполовину, а гейты (`from=daily_plan`, `?optimized=false`,
   `extra_js`) молча оставляли код недостижимым вместо ошибки.

---

## Базовая линия (Task 1)

Прогон 2026-08-08, ветка `cross-zone-audit-remediation`, HEAD `740d80d5`, рабочее дерево чистое
(предсуществующая модификация `scripts/generate_reading_annotations.py` закоммичена в `740d80d5`,
вне зоны аудита).

| Метрика | Значение | Где зафиксировано |
|---|---|---|
| pytest (полный) | 9908 собрано · **27 FAILED** · 9803 passed · 69 skipped · 4 xfailed · 5 xpassed · 0 errors | список nodeid — в baseline-файле, секция «PYTEST» |
| pytest -m smoke | 693 теста · **0 падений** (эталон зелёный) | baseline-файл, секция «КАК СВЕРЯТЬСЯ» |
| ruff `check .` | **4582** нарушения (ruff 0.5.6) | baseline-файл, секция «RUFF» (+ разбивка по каталогам и правилам) |

Полные условия воспроизведения (команда, интерпретатор, почему `-p no:randomly` и почему не xdist) —
в **`docs/audit/2026-08-08-baseline-pytest.txt`**. Там же — готовый рецепт сверки, проверенный на
round-trip против самого этого прогона.

**Уточнение старого счёта:** ранее «известно-красным» числились 26 тестов; фактически их **27** —
добавился `tests/srs/test_counting.py::TestCountRestingWords::test_ignores_short_session_bury`.
Проверено, что он существует и падает на `master` (`git show master:tests/srs/test_counting.py`),
то есть веткой не привнесён.

**Smoke — отдельное правило.** В отличие от полного прогона, smoke в baseline **зелёный**, поэтому
любое падение в нём — регрессия сразу, без сверки со списком.

> **Правило оценки.** «Зелено/красно» определяется **только диффом против baseline-файла**, не по
> абсолютному числу падений. Тест, падающий и до, и после правки — не регрессия. Тест, падающий
> только после — регрессия, блокирует переход к следующей задаче (Development Approach плана).
>
> **NB по ruff — бинарь.** Ruff **не установлен** ни в PATH, ни в `.venv` проекта; единственная
> доступная копия — в кэше pre-commit:
> `/Users/igorkorobko/.cache/pre-commit/repolq0nm4n2/py_env-python3.13/bin/ruff` (0.5.6).
> Сравнивать с baseline **только этим бинарём** — другая версия даёт другое число (ruff меняет
> набор правил между релизами), и дифф станет бессмысленным.
>
> **NB по ruff — область.** `scripts/`, `content/`, `tests/conftest.py` — в `.gitignore`, а ruff по
> умолчанию уважает gitignore, поэтому `ruff check .` их **не видит**. Правки контента из Task 8
> доставляются скриптами в `scripts/` → на канонический счётчик не влияют. Числа по явно переданным
> каталогам (включая gitignored) — в baseline-файле отдельной строкой.

---

## Зона UI

> **Task 2** — закрыт. Шесть линз-финдеров + скептик на КАЖДУЮ находку (56 агентов, 4.1 M токенов,
> 1560 tool-call'ов). Сырых находок **45** → CONFIRMED **30**, REFUTED **15**, PLAUSIBLE 0.
> Плюс перепроверка 13 унаследованных хвостов: **10 подтверждено** (промотированы сюда),
> **3 опровергнуто** (закрыты на месте в секции «Унаследованные хвосты»).
> `C06` и `INH-008` — одна и та же находка (`sentence_completion.html:24`), схлопнуты в `UI-022`.
> Итого зона UI: **30 + 10 − 1 = 39 находок**. Кросс-лензовых дублей по `file:line` — 0.

**Сводка зоны:** P0 — 0 · P1 — 7 · P2 — 10 · P3 — 22.

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. |
|---|---|---|---|---|
| UI-001 | P1 | `app/auth/routes.py:621` | `/change-password` отдаёт 500 — шаблона нет, смена пароля мертва | CONFIRMED |
| UI-002 | P1 | `app/templates/admin/book_courses/edit_lessons_data.html:515` | Весь JS страницы в `{% block extra_js %}`, которого нет в `admin/base.html` → все кнопки мертвы | CONFIRMED |
| UI-003 | P1 | `app/templates/curriculum/book_courses/lessons/final_test.html:371` | Провал POST'а завершения проглатывается, UI пишет «Результат сохранён» | CONFIRMED |
| UI-004 | P1 | `app/templates/words/list_optimized.html:306` | Каждый чекбокс отрисован дважды → «выбрать все» шлёт дубли ID | CONFIRMED |
| UI-005 | P1 | `app/static/js/main.js:94` | `cloneNode` затирает слушатели, навешенные страницей на `.word-checkbox` | CONFIRMED |
| UI-006 | P1 | `app/static/css/books/reader_simple.css:933` | Кнопка возврата аудиоплеера под фиксированным bottom-nav — некликабельна ≤768px | CONFIRMED |
| UI-007 | P1 | `app/templates/curriculum/book_courses/lessons/comprehension_check.html:190` | Ответы book-course уроков — `div onclick` без role/tabindex → клавиатурный тупик | CONFIRMED |
| UI-008 | P2 | `app/templates/curriculum/lessons/matching.html:355` | Jinja `_()` попал дословно в JS → `ReferenceError` убивает обработчик ошибки | CONFIRMED |
| UI-009 | P2 | `app/static/js/linear-plan-context.js:252` | SRS-обзёрвер и `flashcard-session.js` расходятся в `day_secured` на card-уроках | CONFIRMED (был INH-004) |
| UI-010 | P2 | `app/static/js/lesson-completion.js:68` | После грейда фокус не переносится, live-region пишется в скрытый контейнер | CONFIRMED (был INH-007) |
| UI-011 | P2 | `app/templates/curriculum/lessons/vocabulary.html:559` | Личная заметка к слову теряется молча — пустой `catch`, нет `resp.ok` | CONFIRMED |
| UI-012 | P2 | `app/static/js/grammar/topic-detail.js:18` | «Завершить теорию» при ошибке не даёт никакой обратной связи | CONFIRMED |
| UI-013 | P2 | `app/templates/components/_daily_plan_progress.html:104` | План-бар сдвигает страницу дважды: 48px padding + 48px margin | CONFIRMED |
| UI-014 | P2 | `app/static/css/books/reader_simple.css:86` | `height: calc(100vh - 56px)` при ~90–130px хрома → низ читалки за фолдом | CONFIRMED |
| UI-015 | P2 | `app/templates/base.html:436` | Меню «Ещё» в bottom-nav — click-only `div`, с клавиатуры недостижимо | CONFIRMED |
| UI-016 | P2 | `app/templates/base.html:605` | Модалка level-up без `role=dialog`, без фокуса, без Escape, без возврата фокуса | CONFIRMED |
| UI-017 | P2 | `app/static/js/lesson-completion.js:75` | 31 вызов `scrollIntoView({behavior:'smooth'})` игнорирует `prefers-reduced-motion` | CONFIRMED |
| UI-018 | P3 | `app/static/js/main.js:147` | Bulk-update без `X-CSRFToken` → 400, а UI пишет «возможно, применилось» | CONFIRMED |
| UI-019 | P3 | `app/templates/partials/_weekly_report.html:62` | Dismiss недельного отчёта — fire-and-forget, карточка возвращается | CONFIRMED |
| UI-020 | P3 | `app/static/js/flashcard-session.js:874` | `flipCard()` прячет контейнер с фокусом → фокус падает на `<body>` | CONFIRMED |
| UI-021 | P3 | `app/static/js/linear-daily-plan.js:24` | Модалка выбора книги: `aria-modal` есть, переноса и возврата фокуса нет | CONFIRMED |
| UI-022 | P3 | `app/templates/curriculum/lessons/sentence_completion.html:24` | `aria-valuenow` навсегда `0` — JS правит только `style.width` | CONFIRMED (был INH-008) |
| UI-023 | P3 | `app/templates/curriculum/lessons/text.html:646` | `innerHTML` из server/content там, где соседняя ветка использует `textContent` | CONFIRMED (был INH-009) |
| UI-024 | P3 | `app/templates/curriculum/lessons/sentence_correction.html:80` | Single-select через `aria-pressed` вместо `radiogroup`/`aria-checked` | CONFIRMED (был INH-010) |
| UI-025 | P3 | `app/static/css/design-system.css:5109` | Бэкдроп админского sidebar'а полностью прозрачен, но перехватывает тап | CONFIRMED |
| UI-026 | P3 | `app/books/routes.py:120` | `books/add.html` не существует — `?optimized=false` и провал загрузки дают 500 | CONFIRMED |
| UI-027 | P3 | `app/templates/public_base.html:113` | Нет правила `.public-alert--info` — info-флеши на публичных страницах без стиля | CONFIRMED |
| UI-028 | P3 | `app/templates/admin/topics/list.html:16` | Английские заголовки рядом с русскими хлебными крошками в одном шаблоне | CONFIRMED |
| UI-029 | P3 | `app/static/js/linear-plan-context.js:304` | Хардкод русских литералов в 26 из 41 JS-файла в обход `window.I18N` | CONFIRMED (был INH-006) |
| UI-030 | P3 | `app/static/js/linear-plan-context.js:366` | Reader-toast инлайновый; общего toast-примитива в проекте нет (17+ копий) | CONFIRMED (был INH-013) |
| UI-031 | P3 | `app/static/js/daily-plan-next.js:20` | Файл полностью недостижим: гейт ждёт `from=daily_plan`, план шлёт `linear_plan` | CONFIRMED (был INH-001) |
| UI-032 | P3 | `app/templates/lesson_base_template.html:623` | Shim `showLessonCompletion` — единственный путь для всех 15 шаблонов, снять нельзя | CONFIRMED (был INH-003) |
| UI-033 | P3 | `app/api/daily_plan.py:658` | Вложенный `next` — единственная читаемая форма; docstring обещает обратное | CONFIRMED (был INH-005) |
| UI-034 | P3 | `app/templates/components/_flashcard_session.html:375` | Контейнер `#daily-plan-next-step` и событие `dailyPlanStepComplete` без слушателя | CONFIRMED |
| UI-035 | P3 | `app/static/js/dashboard.js:1` | 5 JS-файлов (945 строк) не подключены ни одним шаблоном | CONFIRMED |
| UI-036 | P3 | `app/static/css/dashboard.css:1` | 9 CSS-файлов (~200 KB) не подключены ни одним шаблоном | CONFIRMED |
| UI-037 | P3 | `app/templates/words/dashboard.html:1` | 5 шаблонов-сирот (~1270 строк) не рендерятся ниоткуда | CONFIRMED |
| UI-038 | P3 | `app/templates/components/_path.html:9` | Весь path-дашборд мёртв: 3 шаблона + сервис + ~590 строк CSS + JS | CONFIRMED |
| UI-039 | P3 | `app/static/js/unified-js.js:5` | 421 строка грузится на каждой странице кабинета, 4 из 5 init'ов ни к чему не биндятся | CONFIRMED |

### P1 — детали

**UI-001 · `app/auth/routes.py:621` · шаблон `auth/change_password.html` отсутствует**
Сценарий: залогиненный юзер открывает `/auth/profile`, жмёт «🔑 Изменить пароль»
(`auth/profile.html:212` → `url_for('auth.change_password')`). Хендлер делает
`render_template('auth/change_password.html')`, Jinja бросает `TemplateNotFound`, глобальный
`@app.errorhandler(500)` рендерит `errors/500.html`. POST с корректным паролем **коммитит смену**
и тоже отдаёт 500 — юзер не знает, применилось или нет.
Верификация: `ls app/templates/auth/ | grep change` → пусто; ссылка в профиле существует.

**UI-002 · `app/templates/admin/book_courses/edit_lessons_data.html:515` · `extra_js` не объявлен в базе**
Сценарий: админ открывает `/admin/book-courses/<id>/modules/<id>/lessons-data`. Весь JS страницы лежит
в `{% block extra_js %}`, а `admin/base.html` объявляет только `title` / `extra_css` / `breadcrumb` /
`content` / `scripts`. Jinja выбрасывает блок, которого нет у родителя, поэтому `toggleLesson`,
`removeLesson`, `addLesson`, `saveLessonsData` не определены — каждый `onclick` даёт
`ReferenceError`, редактирование `lessons_data` невозможно. То же на `admin/book_courses/edit.html:602`
(`activateCourse` / `deactivateCourse`).
Верификация: `grep -n "block extra_js\|block scripts" app/templates/admin/base.html` → только
`445: {% block scripts %}`; `grep -rl "block extra_js" app/templates/admin/` → ровно эти два файла.

**UI-003 · `app/templates/curriculum/book_courses/lessons/final_test.html:371` · ложный успех**
Сценарий: юзер завершает финальный тест модуля book-course. POST отдаёт не-2xx (404, если
`BookCourseEnrollment` не найден в `book_courses_api.py:249`; 401 после истечения сессии; 500).
`.catch(e => { console.error(e); showCompletionUI(); })` рендерит **тот же UI, что и ветка успеха** —
«✓ Модуль завершён!» и «Результат сохранён». При этом `UserLessonProgress`, `BookModuleProgress` и
прогресс курса не записаны, модуль остаётся закрытым. Тот же паттерн в `context_review.html:508`,
`comprehension_check.html:325`, `retelling.html:311`, `phrase_cloze.html:382`.

**UI-004 · `app/templates/words/list_optimized.html:306` · каждое слово с двумя чекбоксами**
Сценарий: desktop, `/words`, 20 слов на странице. `.word-checkbox` отрисован дважды — в
`.vocab-table-wrapper` (строка 223) и в `.vocab-mobile-cards` (строка 306), вторая ветка скрыта
только `display:none !important`, узлы остаются в DOM. `toggleSelectAll()` берёт
`querySelectorAll('.word-checkbox')` → 40 узлов; панель показывает «40 слов выбрано» при 20 строках,
`bulkUpdateStatus()` шлёт массив из 40 элементов с каждым id дважды. Зеркальный случай: на 390px
таблица скрыта вместе с единственным `#selectAll` (строка 209) — на мобиле «выбрать все» нет вовсе.

**UI-005 · `app/static/js/main.js:94` · `cloneNode` срывает слушатели страницы**
Сценарий: `/words` рендерит `words/list_optimized.html`; инлайновый `<script nonce>` парсится и
регистрирует свой `DOMContentLoaded` первым, `main.js` объявлен `defer` (`base.html:398`) и
регистрируется вторым. На `DOMContentLoaded` шаблон вешает `change → updateBulkActionsPanel` на
каждый `.word-checkbox` (строки 847–850), после чего `enhancedBulkActionsSetup()` подменяет каждый
узел копией `cloneNode(true)`, которая слушателей не несёт. Отметка одиночного чекбокса больше не
открывает панель массовых действий. То же на `books/words_optimized.html:588`.

**UI-006 · `app/static/css/books/reader_simple.css:933` · кнопка под bottom-nav**
Сценарий: юзер на 390×844 открывает `/books/<id>/read`, закрывает аудиобар («×»,
`data-action="hide-audio-bar"`). `hideAudioBar()` показывает `.rdr-audio-show` и пишет
`localStorage.rdr_audio_visible='hidden'`. Кнопка — `position:fixed; bottom:1rem; right:1rem;
40×40; z-index:100`, то есть занимает y = [bottom+16, bottom+56]. `.bottom-nav` (рендерится
`base.html` каждому аутентифицированному юзеру) — `position:fixed; bottom:0; background:#ffffff;
z-index:1040`, высотой ≥52px (до ~82px на iPhone с `env(safe-area-inset-bottom)`). Кнопка целиком
под непрозрачной панелью с большим z-index → аудиоплеер не вернуть, состояние переживает
перезагрузку и смену главы.
⚠️ Стоит на арифметике по декларированным токенам, без рендера (см. критик-агента) — при ремедиации
проверить в браузере первым делом, вместе с UI-014.

**UI-007 · `app/templates/curriculum/book_courses/lessons/comprehension_check.html:190` · клавиатурный тупик**
Сценарий: юзер открывает book-course урок типа `comprehension_check` с вопросом `multiple_choice` и
ходит только по Tab. `showQuestion()` пишет в `optionsList.innerHTML` набор
`<div class="cc-quiz__option" onclick="selectOption(i)">` — не фокусируемый, без `keydown`. Tab
проскакивает мимо всех вариантов на `#next-btn`, который `disabled`, пока ответ не выбран
(строка 202). Ответить и продвинуться нельзя. То же в `match_headings.html:139,152`
(`heading-item` / `answer-slot`) и `context_review.html:177,334,342`.
Контраст: курсовой `curriculum/lessons/matching.html:426-449` уже переведён на `role='button'` +
`tabIndex=0` + `keydown` — то есть это немигрированный легаси, а не осознанный паттерн.
Ветка `true_false` доступна (реальные `<button>`), поэтому блокируется первый MC-вопрос, а не урок
с первой строки. `match_headings` достижим без ручного авторинга (тип входит в стандартный план
генератора, `book_course_generator.py:435`).

### P2 — детали

**UI-008 · `matching.html:355`** — `showError(_('Ошибка при загрузке игры. Попробуйте еще раз.'))`
стоит **внутри** `<script nonce="{{ csp_nonce }}">`, но не внутри `{{ }}`/`{% %}`, поэтому Jinja его
не трогает и `_(` уезжает в браузер дословно. Глобального `_` в проекте нет
(`grep "function _(\|window\._\s*=" app/static/js/` → пусто), поэтому `catch`-ветка падает с
`ReferenceError` **до** вызова `showError`. Строка 339 уже скрыла setup-UI → экран пустой: ни
настройки, ни игры, ни ошибки. Спасает только перезагрузка. То же в `study/matching.html:343`.

**UI-009 (был INH-004) · `linear-plan-context.js:252`** — исходный блокер снятия обзёрвера
подтверждён лишь наполовину: `/study/api/complete-session` (`app/study/api_routes.py:906-919`) по-прежнему
**не** отдаёт `daily_plan_ctx`, значит для `/study/cards` обзёрвер несущий. Но card-уроки ctx уже
отдают (`app/curriculum/routes/card_lessons.py:906-909`), и там оба механизма работают по одним
якорям и расходятся в `day_secured`: `flashcard-session.js` рисует CTA, через ~200 мс fetch
обзёрвера резолвится последним и делает hard-redirect, выбрасывая только что отрисованное.

**UI-010 (был INH-007) · `lesson-completion.js:68`** — `LessonCompletion.show()` пишет
`#completion-grade` / `#completion-score` (строки 45–54), пока контейнер ещё `display:none`, и лишь
затем переключает его на `display:block`. Раскрытие скрытого узла не является мутацией содержимого,
поэтому большинство скринридеров молчат; фокус остаётся на нажатой кнопке, а в режиме `plan`
`_hideLegacyFooter()` дополнительно прячет `#lesson-footer`. Юзер не получает сигнала, что урок
закончился. `aria-live` (добавлен в `fb289688`) сам по себе проблему не решает — важен порядок.

**UI-011 · `vocabulary.html:559`** — `.catch(function() {})` глотает всё; при 500 с HTML-телом
`r.json()` реджектится и заметка исчезает без следа, форма остаётся открытой с введённым текстом —
неотличимо от медленного ответа. При 400/403 JSON-конверте `data.ok` undefined → гард на строке 548
ложен, тот же тихий no-op. Идентичный паттерн на строках 655–673 (добавление слова в свой список).

**UI-012 · `grammar/topic-detail.js:18`** — POST `/grammar-lab/api/topic/<id>/complete-theory`:
при 500 с HTML-телом `await response.json()` бросает (ловится на строке 33, только `console.error`);
при JSON-ошибке `data.xp_earned` undefined → гард `if (data.xp_earned > 0)` ложен и весь success-блок
пропускается. В обоих случаях страница визуально не меняется, юзер жмёт снова. Кнопка не
дизейблится на время запроса (эндпоинт идемпотентен, поэтому это P2, а не потеря данных).

**UI-013 · `_daily_plan_progress.html:104`** — на любой странице с `?from=daily_plan` бар
(`position:fixed; top:0; height:48px`) после резолва fetch'а добавляет `.dp-bar--visible` **и**
ставит `document.body.style.paddingTop='48px'`. Правило
`#daily-plan-bar.dp-bar--visible ~ nav.navbar { margin-top: 48px }` добавляет ещё 48px. Итог: бар
на y=0..48, контент с y=48, navbar с y=96 — видимая полоса фона в 48px и вся страница ниже на 96px.

**UI-014 · `reader_simple.css:86`** — `.rdr-wrap { height: calc(100vh - 56px) }` при реальном хроме
над ней ~131px (navbar ~70px + XP-бар ~37px + `py-4` 24px). На 1440×900 нижняя кромка уходит на
975px при вьюпорте 900px. Так как `.rdr-body` — вложенный скроллер (`flex:1; overflow-y:auto`),
внешний документ не двигается, пока не кончится глава, поэтому нижние ~75px читалки постоянно за
фолдом. ⚠️ Тоже арифметика без рендера — верифицировать в браузере вместе с UI-006.

**UI-015 · `base.html:436`** — `#bottom-nav-more` это `<div class="bottom-nav__item bottom-nav__more">`
только с `click`-слушателем (строки 466–469): ни `tabindex`, ни `role`, ни `keydown`. Tab на него не
попадает, Enter/Space не срабатывают. Дочерние ссылки лежат в `#bottom-nav-dropdown`, который
`display:none` до добавления `.bottom-nav__dropdown--open`, поэтому и они вне tab-порядка. Обходной
путь — гамбургер верхнего navbar'а, поэтому P2, а не P1.

**UI-016 · `base.html:605`** — `#levelup-modal` раскрывается через `modal.style.display='flex'`
(строки 639/652) без `role="dialog"`, `aria-modal`, `aria-live` и без `.focus()`. Контент за модалкой
остаётся в tab-порядке (ничего не `inert`/`aria-hidden`), Escape-обработчика нет, а закрытие
(`#levelup-modal-close`, строки 686–690) ставит `display:none`, не возвращая фокус — он падает на
`<body>`.

**UI-017 · `lesson-completion.js:75`** — **31** сайт `scrollIntoView({behavior:'smooth'})`
(финдер насчитал 29; точный счёт — от критик-агента). Глобальный блок
`design-system.css:8614-8622` форсит только `scroll-behavior: auto !important`, что по спецификации
**не применяется**, когда вызывающий явно передал `behavior:'smooth'` в `ScrollIntoViewOptions`.
Юзер с включённым `prefers-reduced-motion` получает анимированный скролл на каждом проверенном
ответе (`grammar.html:518` — раз на упражнение, `matching.html:814`, `text.html:1416,1637` и т. д.).

### P3 — детали (кратко)

- **UI-018** `main.js:147` — POST `/api/batch-update-status` уходит без `X-CSRFToken`, а
  `app/api/words.py:224` не `@csrf.exempt` → 400 всегда. UI на `!response.ok` показывает
  «Server returned an error, but operation may have succeeded. Reloading...» и перезагружает, то есть
  утверждает возможный успех там, где его заведомо нет. Достижимо через
  `/books/<id>/words?optimized=false`.
- **UI-019** `_weekly_report.html:62` — `fetch(...)` без `.then`/`.catch`: при обрыве сети —
  unhandled rejection, при 400 CSRF — молча; строка 68 прячет карточку локально, `dismiss_key` не
  сохранён, карточка возвращается на следующей загрузке дашборда.
- **UI-020** `flashcard-session.js:874` — `flipCard()` ставит `cardFront.style.display='none'`, а
  фокус в этот момент на `#show-answer-btn` внутри него → браузер сбрасывает фокус на `<body>`.
  `#card-back` показывается без `aria-live`/`role="status"` и без `.focus()`. Глобальные шорткаты
  1/2/3 остаются, поэтому P3.
- **UI-021** `linear-daily-plan.js:24` — `openModal()` только снимает `hidden` и ставит
  `aria-hidden="false"`, `.focus()` не зовёт. При `aria-modal="true"` AT ограничивает буфер поддеревом
  диалога, а DOM-фокус остаётся на триггере снаружи. `closeModal()` (строка 33) фокус не возвращает.
- **UI-022** (был INH-008) `sentence_completion.html:24` — `_updateProgress()` (179) и
  `_updateProgressLabel()` (324) правят только `fill.style.width`; `aria-valuenow` остаётся серверным
  `0`. Остальные шаблоны уроков уже чинены (зовут `setAttribute('aria-valuenow', …)`) — этот отстал.
  Плюс серверное расхождение в `books/details.html`: `aria-valuenow` читает ключ `queued`, которого в
  `word_stats` нет, и рендерится пустым.
- **UI-023** (был INH-009) `text.html:646` и др. — `innerHTML` из server/content-значений рядом с
  `textContent`-ветками в той же функции; grammar-lab упражнения пишутся как сырой HTML без
  `sanitize_html`. **Живого cross-user XSS нет** — все писатели этих значений админские (перепроверено).
  Пользовательский вход всё же достигает одного сайта: `quiz.html:1303` делает
  `textEl.innerHTML += 'Ваш ответ: <strong>' + userText + '</strong><br>'`, поэтому ответ вида `a<b`
  отображается на разборе как `a` — юзер не видит, что он написал. Подпретензия «дублирующийся `id`
  в aria-live» **не воспроизвелась**.
- **UI-024** (был INH-010) `sentence_correction.html:80` — single-select через `aria-pressed`
  (переключатель) вместо `radiogroup`/`aria-checked`. **Не by-design:** roving-tabindex/arrow-модели в
  проекте нет нигде, а корректный паттерн уже реализован в соседнем коде. Два файла хуже исходной
  претензии: `listening_immersion.html` объявляет `role=radiogroup` без единого `role=radio`
  ребёнка, а matching-кнопки `final_test.html` вообще не выставляют состояние выбора.
- **UI-025** `design-system.css:5109` — `.sidebar-overlay.show` объявляет только `display:block`;
  правило на 5098 переобъявляет display/position/background/z-index, но не `opacity`, поэтому
  `opacity:0` с 1908 побеждает (сброс висит на `.sidebar-overlay.active`, который админский JS
  никогда не ставит). Оверлей отрисован, но полностью прозрачен: затемнения нет, а следующий тап по
  контенту он перехватывает.
- **UI-026** `app/books/routes.py:120` — `books/add.html` не существует. Два пути: GET
  `/books/content/<id>?optimized=false` (строка 187) и POST, где `process_uploaded_book` бросил
  (строка 120) — во втором случае админ получает 500 вместо флеша «Ошибка обработки файла: …».
  Роут `@admin_required`, поэтому P3. Соседние фоллбэки `books/list.html` и `books/details.html`
  на месте — дыра только одна.
- **UI-027** `public_base.html:113` — `class="public-alert public-alert--{{ category }}"`, а
  `design-system.css` определяет только `--success` (18965), `--danger`/`--error` (18969–18970),
  `--warning` (18974). Категория `info` (например, `flash(..., 'info')` после запроса сброса пароля,
  `app/auth/routes.py:198`) не матчится ничем и рендерится нейтральной коробкой.
- **UI-028** `admin/topics/list.html:16` — русская крошка «Главная / Темы» прямо над английским
  «Manage Topics» и английской шапкой таблицы: эти msgid отсутствуют в скомпилированном ru-каталоге.
  Также `admin/topics/words.html:58`, `admin/collections/list.html:16`, `admin/collections/form.html:38`,
  `admin/topics/form.html:26`, `books/edit_info_with_cover.html:6`.
- **UI-029** (был INH-006) `linear-plan-context.js:304` + ещё 25 JS-файлов — хардкод русских
  литералов в обход `window.I18N`. **Приложение поставляет ровно одну рабочую локаль**, поэтому это
  принятый долг, а не живой дефект: сегодня рендер идентичен задуманному. Взрывается при добавлении
  второй локали — серверные подписи переключатся, JS-инжектированные CTA останутся русскими.
- **UI-030** (был INH-013) `linear-plan-context.js:366-417` — общего toast-примитива в проекте
  **нет**: 8 приватных JS-хелперов + 9 дублей `showToast()` инлайном в шаблонах. Свести не к чему —
  сначала нужен примитив. Смена контракта тоста (тайминг, `prefers-reduced-motion`, z-index против
  sticky bottom-nav) требует ручной правки в 17+ местах.
- **UI-031** (был INH-001) `daily-plan-next.js:20` — **полярность унаследованной записи неверна.**
  Гейт `if (params.get('from') !== 'daily_plan') return;`, а план строит URL через `build_slot_url`
  с `from=linear_plan`; grammar-lab practice не несёт `from` вовсе. Значит файл недостижим целиком
  (баннер, авто-редирект, sticky-bar), хотя грузится и парсится на `books/reader_simple.html:1175` и
  `grammar_lab/practice.html:280`. Оба блока проброса `?from=daily_plan` мертвы по той же причине.
- **UI-032** (был INH-003) `lesson_base_template.html:623` — миграция, обещанная в комментарии самого
  шима, не состоялась: `LessonCompletion.show` не зовёт **ни один** call-site, все 15 шаблонов идут
  через `window.showLessonCompletion`. Снятие шима сломает завершение молча — каждый вызов
  feature-detected (`if (typeof window.showLessonCompletion === 'function')`) и fail-open: урок
  засабмитится и оценится, но экран завершения и CTA не отрисуются, без ошибки в консоли.
- **UI-033** (был INH-005) `app/api/daily_plan.py:658` — **полярность тоже инвертирована**: вложенный
  `next` читают ВСЕ фронтовые потребители этого эндпоинта, плоские `next_slot_*` — никто. Условие
  выхода из docstring («дропнуть, когда все перейдут на плоские поля») недостижимо как написано;
  удаление `payload['next']` сломает SRS-CTA, reader-toast, error-review CTA и план-ссылку на
  результатах финального теста.
- **UI-034** `_flashcard_session.html:375` — `flashcard-session.js:1342` шлёт
  `dailyPlanStepComplete`, но единственный слушатель и единственный писатель
  `#daily-plan-next-step` — `daily-plan-next.js`, который на этой странице не подключён. Контейнер
  всегда пуст, событие уходит в никуда. Связано с UI-031.
- **UI-035** `dashboard.js:1` — 0 ссылок из шаблонов у `dashboard.js`, `book_processing.js`,
  `speech_api.js`, `study-guide.js`, `words/dashboard_path.js`. Видимое следствие: на
  `/books/<id>?optimized=false` `books/details.html:154` рендерит пустой
  `<div id="processing-status" class="card mb-4"></div>` — заполнить его мог только
  `book_processing.js`, поэтому юзер видит вечно пустую рамку.
- **UI-036** `dashboard.css:1` — 0 ссылок у `dashboard.css` (83 KB), `study-guide.css`,
  `lesson-styles.css`, `mobile-reader.css`, `reader.css`, `study.css`, `style.css`,
  `unified-styles.css`, `landing.css`. Правка любого из них не меняет ничего в браузере.
- **UI-037** `words/dashboard.html:1` — сироты: `words/dashboard.html`,
  `admin/curriculum/srs_settings.html`, `books/reading_widget.html`,
  `curriculum/book_courses/lessons/grammar.html`,
  `curriculum/book_courses/lessons/reading_assignment.html`. Ловушка конкретная: правка
  book-course `grammar.html` ничего не меняет, потому что `book_courses.py:455` роутит
  `grammar`/`language_focus` на `language_focus.html`/`grammar_bridge.html`. Бонус:
  `admin/curriculum/srs_settings.html` содержит 387 строк вне блоков и лишний `{% endblock %}` —
  синтаксическая ошибка Jinja, недостижимая из-за мёртвости.
- **UI-038** `components/_path.html:9` — цепочка `_path.html → _path_segment.html → _path_node.html`
  не включается ниоткуда; `.path-*` CSS (`design-system.css:16383-16972`, ~590 строк, 99 правил) и
  `words/dashboard_path.js` не могут сматчиться; `build_dashboard_path()` / `DashboardPath` в
  `path_view.py` без продакшн-вызывающих; `partials/_day_secured_banner.html` тоже никем не включён.
- **UI-039** `unified-js.js:5` — 421 строка тянется на каждой странице кабинета
  (`base.html:400`), но `initializeProgressBars` (`.lesson-progress`), `initializeCompletionButtons`
  (`.btn-complete`), `initializeTooltips` (`#word-tooltip`) и `initializeAnkiCards`
  (`.anki-container`) матчат 0 узлов.

### Опровергнуто скептиками (15 из 45) — не переоткрывать без новых фактов

Значимые опровержения (полный разбор — в транскриптах прогона):

- `study/quiz.html:776` «completeQuiz() без `resp.ok`» — опровергнуто.
- `grammar.html:669` «aria-live строится вместе с содержимым» — опровергнуто.
- Кластер i18n (5 находок): «296 кириллических литералов в 28 JS», «`_lesson_i18n.html` — no-op»,
  «ключ `day_done` никем не читается», «дрейф skip-link между тремя базами», «английские флеши на
  пользовательских роутах» — все опровергнуты как принятый долг при одной локали либо как
  недостижимый сценарий. Живой остаток этого класса — только UI-008 (`ReferenceError`) и UI-029.
- `words/list_optimized.css:1313` «тач-таргеты ужаты до 32–36px» — опровергнуто: в
  `design-system.css` есть **два** блока `@media (hover:none) and (pointer:coarse)`, восстанавливающих
  размер (у финдера была ложная посылка, что блок один и не матчится).
- `bc_phrase_cloze.css:335` «тост под bottom-nav» — опровергнуто.
- `quiz_shared_public.html:1`, `grammar_lab/topics.html:1`, `errors/404.html:1` — три layout-претензии
  («не тот base», «выбор base по аутентификации», «страницы ошибок без layout») опровергнуты как
  осознанные решения.
- `lesson_base_template.html:543` «`daily_plan_next_enabled` никогда не ставится» — опровергнуто в
  этой формулировке; живая часть учтена в UI-031.

---

## Зона Контент

> **Task 3.** ID `CNT-NNN`. Пока пусто.
> Для каждой находки указывается модуль/урок и **выразим ли фикс скриптом в `scripts/`** —
> `content/` gitignored, правки доставляются только скриптом, не коммитом данных.

_(нет находок — зона не просканирована)_

### Точка отсчёта валидаторов

> Task 3 фиксирует здесь актуальный вывод `validate_corpus.py`, `validate_module_completed_json.py`
> и `diff_module_json_against_db.py`. Это **точка отсчёта, а не находки** — находками становятся
> только расхождения сверх неё.

---

## Зона Разделы

> **Task 4.** ID `SEC-NNN`. Пока пусто.
> Каждая находка указывает blueprint и конкретный сценарий отказа. Находки, пересекающиеся с
> реестром `2026-06-13-100-edge-cases.md` (все 102 закрыты), помечаются явно как **регресс**.

_(нет находок — зона не просканирована)_

---

## Зона Админка

> **Task 5.** ID `ADM-NNN`. Пока пусто.
> Линза (г) формулирует находки как **конкретные недостающие метрики/представления**, а не как
> «сделать дашборд лучше».

_(нет находок — зона не просканирована)_

---

## Унаследованные хвосты аудита 2026-06-19

**Статус: ✅ перепроверено в Task 2 (2026-08-08).** Каждый из 13 пунктов settled чтением текущего
дерева четырьмя агентами. Итог: **10 CONFIRMED** → промотированы в `UI-NNN` (см. колонку «Итог»),
**3 REFUTED** → закрыты здесь и в зону не перенесены.

Три содержательные поправки к унаследованным формулировкам (полярность записи была неверна):

- **INH-001** — записано «файл ЖИВОЙ, грузится ридером и grammar-lab». На деле гейт ждёт
  `from=daily_plan`, а план строит `from=linear_plan` → файл недостижим **целиком**.
- **INH-005** — записано «вложенный `next` держится для обратной совместимости». На деле вложенную
  форму читают все потребители, а плоские `next_slot_*` — никто.
- **INH-004** — блокер снятия подтверждён только для `/study/cards`; на card-уроках `daily_plan_ctx`
  уже отдаётся, и там два механизма конфликтуют. Severity поднята с P3 до P2.

| ID | Итог | Куда ушло / почему закрыто |
|---|---|---|
| INH-001 | ✅ CONFIRMED (P3) | → **UI-031** (с исправленной полярностью) |
| INH-002 | ❌ REFUTED | Не воспроизводится: обзёрвер — **единственный** путь раскрытия каталогового футера, то есть несущий, а не мёртвый; когда показывается блок завершения, футер детерминированно гасится `display:none !important`, поэтому конкурирующих CTA не бывает |
| INH-003 | ✅ CONFIRMED (P3) | → **UI-032** |
| INH-004 | ✅ CONFIRMED (P2 ↑) | → **UI-009** |
| INH-005 | ✅ CONFIRMED (P3) | → **UI-033** (с исправленной полярностью) |
| INH-006 | ✅ CONFIRMED (P3) | → **UI-029** (охват расширен: 26 из 41 JS-файла) |
| INH-007 | ✅ CONFIRMED (P2) | → **UI-010** |
| INH-008 | ✅ CONFIRMED (P3) | → **UI-022** (схлопнуто с находкой линзы a11y `C06` — тот же `file:line`) |
| INH-009 | ✅ CONFIRMED (P3) | → **UI-023**. Перепроверено: живого cross-user XSS **нет**; подпретензия «дублирующийся `id`» не воспроизвелась; зато найден пользовательский вход в sink (`quiz.html:1303`) |
| INH-010 | ✅ CONFIRMED (P3) | → **UI-024**. Гипотеза «by-design из-за arrow-навигации» **отвергнута** — roving-tabindex нет нигде |
| INH-011 | ❌ REFUTED | Противоречие исходного реестра разрешено: права секция **A5** — fetch-конверсия (`715877c6`) в дереве есть, `<form>` в `final_test.html` не осталось (grep даёт 0), XHR-ветка сервера отдаёт JSON `attempts_exhausted`. Абзац «частично / открыто» — устаревший |
| INH-012 | ❌ REFUTED | Посылка верна (GET `writing_prompt` действительно не передаёт `daily_plan_ctx`), вывод — нет: app-level context processor `_inject_daily_plan_ctx` (`app/__init__.py:440-486`) инжектит ctx во все рендеры `curriculum_lessons.*`, поэтому переменная всё равно заполнена |
| INH-013 | ✅ CONFIRMED (P3) | → **UI-030** (уточнено: общего toast-примитива в проекте нет вовсе) |

Исходная таблица seed'а (формулировки на момент Task 1) — ниже, для истории.

| ID | Зона | Файл(ы) | Sev (унасл.) | Симптом | Что перепроверить |
|---|---|---|---|---|---|
| **INH-001** | UI | `app/static/js/daily-plan-next.js` | P3 | Stage 4 dead-code: файл **живой** — грузится ридером (`books/reader_simple.html`) и grammar-lab practice через `?from=daily_plan`; на уроках уже отключён Jinja-флагом `daily_plan_next_enabled`. Мёртв только внутри уроков | Действительно ли остались недостижимые ветки (mission-код убран в `715877c6`); жив ли sticky-bar `#daily-plan-bar`. **Не удалять файл** без grep всех include'ов |
| **INH-002** | UI | `app/templates/lesson_base_template.html` | P3 | Stage 4 dead-code: легаси `#lesson-footer` + MutationObserver — второй конкурирующий completion-механизм рядом с `showLessonCompletion` | Рендерится ли `#lesson-footer` хоть одним шаблоном; биндится ли observer |
| **INH-003** | UI | `app/templates/lesson_base_template.html` (inline `showLessonCompletion`) | P3 | Stage 4 dead-code: inline `showLessonCompletion` — тонкий shim поверх `app/static/js/lesson-completion.js` | Все ли вызывающие шаблоны переведены на `LessonCompletion.show`; можно ли снять shim без слома |
| **INH-004** | UI | `app/static/js/linear-plan-context.js` (`applySrsPlanAwareCompletion` + SRS MutationObserver) | P3 | Stage 4 dead-code: SRS-обзёрвер перестраивает те же якоря, что правит `completeSession` in-place | **Блокер снятия:** нужен `daily_plan_ctx` в ответе `/study/cards` complete — иначе SRS теряет план-CTA. Проверить, появился ли ctx |
| **INH-005** | UI | `app/api/daily_plan.py` (`/api/daily-plan/next-slot`) | P3 | Stage 4 dead-code: back-compat вложенный ключ `next` рядом с flat-DTO | Есть ли ещё потребители вложенной формы (grep по фронту) |
| **INH-006** | UI | `linear-plan-context.js` (`applySrs*`, `applyErrorReview*`, reader-toast) | P3 | JS i18n routing: инфраструктура `window.I18N` готова (`app/templates/components/_lesson_i18n.html`), но эти хелперы всё ещё с русскими литералами | Полнота списка непереведённых литералов по всему `app/static/js/**`, не только в этом файле |
| **INH-007** | UI | `app/templates/lesson_base_template.html` + шаблоны с блоками результата | P2 | a11y-хвост: нет focus-management после грейда — фокус остаётся на кнопке, результат не объявляется целевым образом (`aria-live` уже добавлен в `fb289688`) | Есть ли `tabindex=-1` + `.focus()` на блоках результата |
| **INH-008** | UI | прогресс-бары уроков | P3 | a11y-хвост: `aria-valuenow` объявлен в разметке, но JS обновляет только `style.width` | Список шаблонов, где `aria-valuenow` расходится с реальным прогрессом |
| **INH-009** | UI | `text` / `grammar` / `quiz` / `sentence_*` / `dictation` / `audio_fill_blank` / `pronunciation` / `listening_immersion` / `final_test` | P2 | a11y-хвост + XSS-долг: `innerHTML` из server/content-значений там, где соседние ветки используют `textContent`; перерисовка aria-live с дублирующимся `id`; grammar-упражнения не проходят `sanitize_html` | Живого cross-user XSS нет (контент админский) — подтвердить, что это по-прежнему так; собрать точный список мест |
| **INH-010** | UI | `final_test.html` · `sentence_correction.html` · `listening_immersion.html` | P3 | a11y-хвост (семантика, клавиатура работает): `aria-pressed` на matching-кнопках вместо `role=radiogroup`/`aria-checked` для single-select | Не является ли это осознанной UX-моделью (arrow-навигация) — тогда P3 → закрыть как by-design |
| **INH-011** | UI | `app/templates/curriculum/lessons/final_test.html` | P2 | `final_test` hidden-form POST без обработки ошибок: 4-я/исчерпанная попытка флешится и редиректится, **теряя результат** | ⚠️ **Реестр 2026-06-19 сам себе противоречит:** секция A5 помечена ✅ «переведён на fetch (`715877c6`)», а более ранний абзац «Частично / открыто» всё ещё числит это хвостом. Прочитать текущий `final_test.html` и разрешить противоречие |
| **INH-012** | UI / Разделы | `app/curriculum/routes/lessons.py` (GET writing_prompt) + `writing_prompt.html` | P2 | `writing_prompt` reload state: GET-роут не строит `daily_plan_ctx` → reload завершённого урока без `?from` рендерит `is_daily_plan:False` → каталоговые CTA вместо план-CTA | Строится ли ctx сейчас; сравнить с `sentence_completion_lesson`, который его строит |
| **INH-013** | UI | `app/static/js/linear-plan-context.js` (reader toast) | P3 | Reader-toast не вынесен в общий примитив и не переведён | Есть ли уже общий toast-примитив, к которому его свести |

**Не перенесено в seed (осознанно):** закрытые в `2026-06-19` находки (A4, A5-основная часть, A6 все 6 типов,
A11, matching P0, grammar `retryLesson`/match-skip, card `examples`, score/XP-кластер) и принятый
остаточный долг P3 `check-item final:true` — он задокументирован в исходном реестре как **принятое**
поведение, а не открытый хвост. Если Task 2–4 наткнутся на любой из них заново — это **регресс**,
и он оформляется новой находкой с явной пометкой «регресс к `2026-06-19`».

> **Стале в исходном реестре (учтено при seed'е):** список «Открыты: #1, #3, #4, #6, #7, #10» в
> секции «Часть C — Quick wins» устарел — #1 (matching P0), #3 (card examples), #4 (`retryLesson`),
> #6 (grammar match-skip) закрыты позднее коммитом `b41b1563`, #7 (`resp.ok`) — в `6fa04cfc`/`c7b92cad`.
> Поэтому в seed они не попали.

---

## Приложение: PLAUSIBLE

> Находки, которые скептик **не смог доказать**, но и не опроверг окончательно. В основной реестр не
> входят, в ремедиацию не берутся. Держатся здесь, чтобы следующий аудит не открывал их с нуля.

### Зона UI (Task 2)

Скептический проход дал **0 PLAUSIBLE** — каждая из 45 находок легла либо в CONFIRMED (30), либо в
REFUTED (15). Ниже — то, что **не проходило через скептика** и потому не может быть записано как
CONFIRMED: находки, срезанные капом в 8 штук на линзу, и то, что нашёл критик-агент на полноту.
Всё это — кандидаты первой очереди для следующего прохода, а не подтверждённые дефекты.

| # | Файл:строка | Откуда | Претензия |
|---|---|---|---|
| PL-UI-01 | `app/static/js/books/content_editor_optimized.js:207` | критик | `autoSave()` на debounce `setTimeout(autoSave, 2000)` (строка 17) зовёт `markAsSaved()`, показывает тост «сохранено» и сбрасывает `hasUnsavedChanges`, **не отправляя ни одного запроса**. Если подтвердится — потеря контента книги, severity выше P2. Файл живой (`books/content_editor_optimized.html:146`) |
| PL-UI-02 | `app/templates/partials/unified_daily_plan.html:429` | срезано капом a11y | `.plan-item__skip-btn` переключает `reasonsDiv.hidden` (скрипт 673–682), но не ставит `aria-expanded` |
| PL-UI-03 | `app/templates/base.html:227` | срезано капом a11y | `#notif-bell` без `aria-expanded` / `aria-controls` |
| PL-UI-04 | `app/templates/base.html:105,201` | срезано капом a11y | `aria-label` на контейнере глушит счётчики-бейджи внутри |
| PL-UI-05 | `app/templates/curriculum/lessons/grammar.html:92,166` | линза адаптива, сознательно не заведено | `.grammar-table` с `width:100%` без `overflow-x`-обёртки, в отличие от соседних `.theory-table-wrapper` / `.vocab-table-wrapper` |
| PL-UI-06 | `app/templates/curriculum/lessons/pronunciation.html:328` | линза fetch, сознательно не заведено | `.catch(() => {})` на per-item POST в связке с 400 `requires_attempt` на `finish=true`; одношаговый сценарий отказа построить не удалось |
| PL-UI-07 | границы `1023/1024` и `640/641` | линза адаптива, сознательно не заведено | `@media (max-width: 1023px)` без парного `min-width` оставляет субпиксельную полосу на дробных вьюпортах |

**Дисциплина:** ни один пункт этого приложения не идёт в Task 7–9. Чтобы попасть в ремедиацию,
находка должна пройти скептика в следующем проходе аудита.

---

## Покрытие и сознательные пропуски

> Заполняется по мере прохождения Task 2–5; Task 6 добавляет сюда результат критик-агента на полноту
> (какая линза не запускалась, какое утверждение не проверено, какой файл не прочитан).

| Зона | Просканировано | Сознательно не покрывалось | Причина |
|---|---|---|---|
| UI | Шаблоны: ~96 из 248 (без `emails/`) поимённо прочитаны — `lesson_base_template.html`, `base.html`, `public_base.html`, `admin/base.html`, 17 из 20 `curriculum/lessons/**`, 6 из 21 `curriculum/book_courses/lessons/**`, `partials/**`, `components/**` (кроме трёх), `auth/**` (кроме четырёх), `words/list_optimized.html`, `books/reader_simple.html`. JS: 26 из 40 не-вендорных. CSS: `design-system.css` (19 257 строк) целиком по правилам + `books/reader_simple.css`, `words/list_optimized.css`, `lessons/bc_phrase_cloze.css`, `flashcard-session.css`. Машинные проходы по всем 265 шаблонам: extends-граф, резолюция `_()`, извлечение кириллицы, `grep` по `fetch(`/`onclick=`/`innerHTML`/`role=progressbar` | `app/templates/admin/**` (94 из 102), `app/templates/study/**` (18 из 26), `curriculum/**` верхний уровень целиком, `books/list_optimized.html` + `details_optimized.html` (дефолтные!), подзоны `race/`, `modules/`, `onboarding/`, `landing/`, `legal/`, `feedback/`, `grammar_lab/{practice,stats}`; 14 JS-файлов (в т.ч. `share.js` — грузится на **каждой** странице обеих layout-веток); 69 из 98 CSS-файлов; `emails/**`; вендор `bootstrap.*` | Админка вынесена в Task 5 (эта линза покрыла только общий хром + два `extra_js`-дефекта). Остальное — кап в 8 находок на линзу плюс инструкция концентрироваться на highest-traffic learner-поверхностях. `emails/**` и вендор — вне зоны по брифу |
| Контент | — | — | — |
| Разделы | — | — | — |
| Админка | — | — | — |

### Критик-агент на полноту (зона UI, Task 2)

Прогон отдельного агента, читающего не код, а **сам аудит**: что осталось непрочитанным и какое
утверждение стоит на скрипте, а не на чтении. Результат приведён без смягчения.

**Утверждения без доказательства (подлежат перепроверке в следующем проходе):**

- Линза fetch написала «`books/*.js` — нет fetch». **Опровергнуто:**
  `books/content_editor_optimized.js:181` — `await fetch('', {method:'POST', body: formData})`, файл
  живой. Там же находка PL-UI-01.
- «`curriculum/book_courses/lessons/*.html` (все 19)» — в каталоге 20 уроков + `_lesson_base.html`;
  число не сходится, поимённо названо 5.
- «`curriculum/lessons/*.html` (все 20)» — перечислено 17; `card.html` (реально рендерится),
  `empty_content.html`, `final_test_results.html` не названы.
- Шесть шаблонов с `fetch(` не попали ни в scanned, ни в not_covered: `base.html`,
  `lesson_base_template.html`, `words/details_optimized.html`,
  `curriculum/book_courses/course_detail.html`,
  `curriculum/book_courses/lessons/_lesson_base.html`, `admin/quiz_decks/list.html`.
- «29 сайтов `scrollIntoView` smooth» — фактически **31**; 12 из них в шаблонах, которых нет в
  scanned-списке линзы a11y. (Число в UI-017 исправлено на 31.)
- Layout-линза: «построен extends-граф всех 265 шаблонов» — результат скрипта, поимённо прочитано
  ~35. Вывод «какой base наследует страница» доказан; вывод «страница выглядит правильно» — нет.
- i18n-линза: литералы 24 JS-файлов свёрнуты в одну находку и построчно не верифицированы
  (например `share.js:83` `'Скопировано!'` — глобально подключённый файл, никем не открытый).
- **UI-006 и UI-014 (обе по ридеру) стоят на арифметике по декларированным токенам, без рендера.**
  Единственные P1/P2 в таком статусе — проверять первыми.
- Не разобрано пофайлово: 174 `onclick=` вне admin и 528 вхождений `innerHTML` — только grep.

**Перепроверено критиком независимо и подтверждено** (переобход не нужен): 9 неподключённых
корневых CSS, 5 неподключённых JS, мёртвость `admin/curriculum/srs_settings.html`, 463 сайта
`flash()`, факт что `books/{list,details,words}.html` рендерятся только при `?optimized=false`.

**Приоритет следующего прохода по UI** (порядок — от критика):
1. `books/content_editor_optimized.js:207` — подтвердить потерю контента при автосохранении.
2. `share.js` — единственный JS на всех страницах обеих веток, ноль прочтений.
3. Дефолтные книжные страницы `books/list_optimized.html`, `details_optimized.html`, `read_selection.html`.
4. `study/insights.html` (660 строк, 5 `<script>`) и `study/index.js`.
5. Нетронутые подзоны с живыми роутами: `race/`, `modules/`, `onboarding/`, `feedback/`, `grammar_lab/`.
6. Навигационный костяк курса: `curriculum/{index,level_modules,module_lessons,search,public_*}.html`,
   `book_courses/{list,course_detail,module_detail}.html`.
7. 15 book-course уроков, покрытых только формулировкой «все 19», и `curriculum/lessons/card.html`.
8. Админские шаблоны с `fetch(` — но это уже область Task 5.

---

## План ремедиации

> Заполняется в **Task 6**: списки ID для Task 7 (все P0), Task 8 (все P1), Task 9 (отобранные P2),
> и явный список отложенного с причиной.

| Задача | Состав | Статус |
|---|---|---|
| Task 7 — P0 | _(Task 6)_ | ⬜ |
| Task 8 — P1 | _(Task 6)_ | ⬜ |
| Task 9 — отобранные P2 | _(Task 6)_ | ⬜ |
| Отложено (P3 + рискованные P2) | _(Task 6)_ | ⬜ |

---

## Статус ремедиации

> Заполняется в Task 7–9 по мере закрытия находок. Формат — как в
> `2026-06-19-daily-plan-lesson-frontend-audit.md`.

| Находка | Что сделано | Как | Коммит |
|---|---|---|---|
| _(пусто — ремедиация не начата)_ | | | |

---

## Verification

- Полный `pytest`, диффом против `docs/audit/2026-08-08-baseline-pytest.txt` — **ноль новых падений**
  (рецепт сверки — в самом baseline-файле, секция «КАК СВЕРЯТЬСЯ»).
- `pytest -m smoke` (693 теста) — все зелёные; baseline здесь зелёный, поэтому любое падение = регрессия.
- `ruff check .` — ≤ 4582 нарушения, тем же бинарём 0.5.6 из кэша pre-commit.
- `python -c "import app"` — импорт чист.
- `scripts/validate_corpus.py` — 0 errors в корпусе.
- Каждая находка реестра имеет финальный статус (✅ / 🟡 / ⬜).
