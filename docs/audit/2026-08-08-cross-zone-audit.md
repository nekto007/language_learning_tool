# Сквозной аудит 4 зон — 2026-08-08

> Реестр находок сквозного аудита: **UI · Контент · Разделы · Админка**.
> План: `docs/plans/2026-08-08-cross-zone-audit-remediation.md`.
> Образцы формата: `docs/audit/2026-06-19-daily-plan-lesson-frontend-audit.md`,
> `docs/audit/2026-06-13-100-edge-cases.md`.
>
> **Принцип:** аудит не правит код (Task 1–6), ремедиация не переоткрывает аудит (Task 7–9).
> Между ними — гейт консолидации: находки дедуплицируются и перепроверяются скептиками;
> в реестр идут только **CONFIRMED**, **PLAUSIBLE** — в приложение.

**Статус:** 🟠 Task 1–5 закрыты (каркас + baseline + зона UI: **39 находок**; зона Контент:
**33 находки**, 0 P0 / 9 P1 / 13 P2 / 11 P3; зона Разделы: **8 находок**, 0 P0 / 3 P1 / 0 P2 / 5 P3;
зона Админка: **8 находок**, 0 P0 / 1 P1 / 4 P2 / 3 P3). Всего **88**.
Дальше — Task 6 (кросс-зонная дедупликация, второй проход верификации, план ремедиации).

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
| P0 | 0 | 0 | 0 | 0 | 0 | 0 |
| P1 | 7 | 9 | 3 | 1 | 0 | 20 |
| P2 | 10 | 13 | 0 | 4 | 0 | 27 |
| P3 | 22 | 11 | 5 | 3 | 0 | 41 |
| **Всего** | **39** | **33** | **8** | **8** | **0** | **88** |

**Корневые темы зоны Админка:**

1. **Гейт проверяет по литеральному списку, и список отстал от кода.** `ADM-002`:
   `ADMIN_BLUEPRINT_PREFIXES` — константа из 15 строк, ничем не сверяемая с фактическим набором
   blueprint'ов под `/admin`; пять неймспейсов родились после неё и в проверку не попали.
   Тот же класс, что `CNT-004`/`CNT-011` в зоне Контент: инструмент печатает зелёный именно там,
   где дефект. Здесь он ещё и точно совпал с самым необратимым действием админки — публикацией
   в канал и массовой рассылкой.
2. **Два эндпоинта на одном URL — победитель выбирается порядком регистрации.** `ADM-001`
   (реальная поломка: автокомплит потерял 49% словаря) и `ADM-006` (шесть безвредных дублей,
   но правка в перекрытом файле молча не сработает). Ни один из 14 дублирующихся URL не ловится
   тестом; `url_for` на проигравший эндпоинт строится успешно и уводит на чужой хендлер.
3. **Инструмент написан, вход в него не проложен.** `ADM-004`: четыре формы редактирования
   упражнений существуют, но ссылки на них нет ни в одном шаблоне — админ правит те же данные
   сырым JSON. Зеркало `CNT-005`/`CNT-016` («механизм есть, данных/пути под ним нет»).
4. **Дашборд измеряет то, что легко посчитать, а не то, что ломается.** `ADM-003`: шесть
   coverage-метрик, из которых две структурно нулевые у 16 типов из 17, — и ни одной из
   33 находок зоны Контент. `missing_audio_count = 0` при 1570 мёртвых ссылках на аудио слов.
5. **Конвенция применена там, где её вводили, и не размножена.** `ADM-007` (аудит есть у 2 из 7
   экспортов), `ADM-008` (`get_*_arg` в 2 из 19 модулей, `escape_like` мимо 4 живых `ilike`).
   Тот же корень, что тема 1 зоны Разделы: не «забыли написать защиту», а «забыли позвать
   существующую».

**Корневые темы зоны Разделы:**

1. **Гейт написан один раз и не размножен на соседние роуты.** `SEC-001`: в одном файле
   `app/api/books.py` пять эндпоинтов зовут `can_user_access_book` + `_draft_hidden`, а три
   (`/tasks/<id>`, `/blocks/<id>`, `/blocks/<id>/tasks`) — ни одного. Слой доступа к книгам
   (`app/books/access.py`) построен и отлажен прошлыми аудитами (E-047/E-048/E-050), но покрытие
   роутов держится на дисциплине автора, а не на конструкции: нет ни `before_request` на blueprint'е,
   ни теста «каждый роут `api_books` дёргает гейт».
2. **Хелпер безопасности есть, но применён выборочно.** `SEC-002`: `get_safe_redirect_url` зовётся
   в 6 местах, а `?from=` в ридере подставляется в `href` сырым, в двух роутах. Тот же класс, что
   тема 1: не «забыли написать защиту», а «забыли позвать существующую».
3. **Имя эндпоинта — единственный контракт, и он ничем не проверяется.** `SEC-003`, `SEC-004`,
   `SEC-005`, `SEC-008`: четыре `url_for` на эндпоинты, которых нет в `url_map`. Ошибка вылезает
   только в рантайме (`BuildError` → 500) и только на той ветке шаблона/хендлера, которая
   отрисовывается редко (пустое состояние колоды, исчерпанные попытки, легаси-редирект).
   Ни один не ловится тестами.
4. **Заглушка живёт как продовый роут.** `SEC-006`: `/api/book/<id>/content` отдаёт захардкоженный
   «Sample book content would go here…» под `@api_auth_required`. Прототип не был ни удалён,
   ни закрыт флагом.

**Корневые темы зоны Контент:**

1. **Инструмент проверки слеп ровно там, где дефект.** `CNT-004` (обходчик аудио не видит 83%
   ссылок → 1570 отсутствующих файлов рапортуются как `missing=0`), `CNT-011` (валидатор молча
   пропускает схему и печатает PASS), `CNT-012` (29 ложных ошибок), `CNT-013` (JSON↔БД diff вообще
   не запускается). Четыре из пяти гейтов корпуса дают ложно-зелёный сигнал — поэтому «0 errors»
   в базовой линии ничего не гарантирует.
2. **Генератор оставил швы, а чистка шла по списку известных строк.** `CNT-006`, `CNT-007`,
   `CNT-024`, `CNT-025`, `CNT-026`: `validate_corpus.py` ловит фиксированный словарь фраз, и всё,
   чего в словаре нет, пережило семь проходов ремедиации 2026-06-18.
3. **Один и тот же пул предложений в четырёх обёртках.** `CNT-022` (98% пар коллокаций —
   предложения из словаря), `CNT-023` (66 модулей `shadow_reading`), `CNT-009` (mail-merge-диалоги).
   Кросс-модульный рециклинг закрыт прошлым аудитом, внутримодульный — нет.
4. **Тип упражнения авторится там, где рендер его не поддерживает.** `CNT-001` (matching в финальном
   тесте — два разошедшихся обработчика), `CNT-002` (matching в чтении — ветки нет вовсе),
   `CNT-031`. Контент и шаблон эволюционировали врозь, и ни один валидатор не сверяет тип
   упражнения с тем, умеет ли его отрисовать конкретный шаблон.
5. **Данные, на которых стоит гейтинг, не заполнены.** `CNT-005` (ни один входной модуль уровня не
   несёт prerequisites — при том что код прямо документирует их как единственную защиту),
   `CNT-014` (формат prerequisites не парсится), `CNT-017`/`CNT-018`/`CNT-019` (пустые и
   полузаполненные таблицы метаданных). Механизм написан, данных под ним нет.

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

> **Task 3** — закрыт. Четыре линзы-финдера (остатки bulk-генератора · непроходимые упражнения ·
> покрытие медиа/метаданных · целостность прогрессии) + скептик. Записано **33 находки**
> `CNT-001…CNT-033`: 0 P0 / 9 P1 / 13 P2 / 11 P3.
> Каждая находка указывает модуль/урок и **выразим ли фикс скриптом в `scripts/`** — корпус
> (`module_completed/fixed/`, `content/`) **gitignored**, правки доставляются только скриптом.
>
> **Где живёт корпус.** Вопреки формулировке плана («`content/` — 86+ модулей JSON»), исходники
> модулей лежат в **`module_completed/fixed/*.json`** (86 файлов, 1548 уроков, `.gitignore:402`).
> `content/` содержит только immersion-сиды и словари. Контракт — `docs/design/module-source-json-contract.md`.
>
> **Дисциплина понижений.** Три претензии финдеров понижены после проверки первоисточника, а не
> приняты на веру: см. `CNT-024` (P1→P3, «наполнитель финального теста» — вкладка не отдаётся
> рендером), `CNT-030` (P1→P3, ordering-токены), и опровергнутые в конце секции.

### Точка отсчёта валидаторов

> Не находки, а базовая линия. Находками становятся только расхождения сверх неё.

| Инструмент | Команда | Результат 2026-08-08 |
|---|---|---|
| `validate_corpus.py` | `PYTHONPATH=. python scripts/validate_corpus.py` | 86 модулей · 1548 уроков · 17 типов · 8274 audio-ref · **0 errors / 0 warnings** · `✅ PASS` |
| `validate_module_completed_json.py` | `PYTHONPATH=. python scripts/…` | 86 модулей · **errors=29 · warnings=2** · audio_assets=1306 (missing=0) · exit 0 (без `--strict` — так задокументировано) |
| `audit_module_completed_json_gaps.py` | `PYTHONPATH=. python scripts/…` | **1 canonical / 85 needs-work** — все 85 из-за отсутствия `sentence_correction` |
| `diff_module_json_against_db.py` | только через обход (`CNT-013`) | 86/86 модулей сматчены · 1548/1548 уроков по `external_key` · **0 json-only · 0 db-only · 0 position-collisions** |

**Все 29 «ошибок» второго валидатора — ложноположительные** (`CNT-012`). **JSON↔БД: содержательного
дрейфа 0** — независимая посимвольная сверка `content` для всех 1548 уроков (`CNT-000` ниже).

**CNT-000 · JSON↔БД drift · базовая линия, не находка.** Сверены `content`, `title`, `type` всех 1548
уроков против `learn_db_prod`. Содержательных расхождений — **0**; расходятся только два
несемантических ключа: `content.xp_reward` (импортёр вписывает своё значение; в коде не читается —
`lessons` не имеет колонки `xp_reward`) и `exercises: []`, который импортёр добавляет 77 финальным
тестам. `type`: источник декларирует `flashcards`, БД хранит `card` — **равномерно для всех 172**
уроков, оба алиаса обрабатываются (`_CARD_LESSON_TYPES`, `LESSON_TYPE_TO_SOURCE`), дефекта нет.
**Вывод: реимпорт по итогам Task 3 не требуется ни для одного модуля** (в отличие от предположения
в Post-Completion плана).

### Индекс

| ID | Sev | Модуль/файл | Симптом | Вериф. |
|---|---|---|---|---|
| CNT-001 | P1 | `module_completed/fixed/*.json` L18 (86/86) | 105 `matching`-вопросов финальных тестов **всегда** засчитываются неверно | CONFIRMED |
| CNT-002 | P1 | 14 модулей, L6 `reading` | `matching`-упражнение рендерится как пустое текстовое поле — мёртвый вопрос | CONFIRMED |
| CNT-003 | P1 | все 86 модулей, L1/L2/L14 | 1570 `pronunciation_en_*.mp3` не существуют → кнопка озвучки мертва у 1498 из 1580 слов курса | CONFIRMED |
| CNT-004 | P1 | `scripts/validate_module_completed_json.py:286` | Обходчик аудио слеп к 83% ссылок → `missing=0` ложно, весь CNT-003 невидим | CONFIRMED |
| CNT-005 | P1 | `modules` (БД), 4 входных модуля уровней | Ни один входной модуль уровня не несёт `prerequisites` → очередь предлагает A2 M1 юзеру, не добившему A1 M2 | CONFIRMED |
| CNT-006 | P1 | 33 модуля, L1 `vocabulary` | 196 примеров с приклеенным «It appears during focused classroom practice.» | CONFIRMED |
| CNT-007 | P1 | 18 модулей, L6 `reading` | 174 строки текста с «This reading version adds context one.» | CONFIRMED |
| CNT-008 | P1 | `module_A2_7_healthy_lifestyle.json` L8 + `module_A2_4_food_cooking.json` L18 | 5 аудиофайлов делятся двумя модулями с разными ответами — 4 из 6 вопросов урока звучат не про то | CONFIRMED |
| CNT-009 | P1 | 55 модулей, L12 `dialogue_completion_quiz` | Mail-merge-фразы: правильным ответом объявлен неграмотный английский («Yes, I have a brown.») | CONFIRMED |
| CNT-010 | P2 | 32 модуля (13 A1 + 19 A2), L17 `writing_prompt` | A1-набор `target_phrases` на чужих заданиях гейтит завершение | CONFIRMED |
| CNT-011 | P2 | `scripts/validate_corpus.py:55` | При задокументированном запуске тихо пропускает рантайм-схему и всё равно печатает `✅ PASS` | CONFIRMED |
| CNT-012 | P2 | `scripts/validate_module_completed_json.py:479` | 29 ложных `empty-required-field`: пустой ведущий `prompt` — легальная форма | CONFIRMED |
| CNT-013 | P2 | `scripts/diff_module_json_against_db.py:696` | DB-ветка мертва: `create_app("development")` + чужой инстанс `db` | CONFIRMED |
| CNT-014 | P2 | `modules.prerequisites` (2 строки) | Формат `["module_10"]` парсер не понимает → оба авторских чекпоинта — no-op | CONFIRMED |
| CNT-015 | P2 | 86 `audio_fill_blank` + 24 урока с `0` | Нет `duration_seconds` → слушание засчитывается по 300 с вместо ~52 с (×6) | CONFIRMED |
| CNT-016 | P2 | 85 из 86 модулей | Нет обязательного канонического типа `sentence_correction` — тип реализован, но недостижим | CONFIRMED |
| CNT-017 | P2 | `word_collocations`, `cultural_notes` (БД) | Обе таблицы пусты — фича «pills» не рендерится никогда, 2 лишних запроса на урок | CONFIRMED |
| CNT-018 | P2 | `collection_words` (БД) | Метаданные слова — 19.7% всего / 56.2% на словах курса; один прерванный backfill | CONFIRMED |
| CNT-019 | P2 | `collection_words` (БД) | 1908 строк с литералом `["null"]`, замаскированных `_clean_word_list` | CONFIRMED |
| CNT-020 | P2 | 13 модулей | Уровень лексики не совпадает с уровнем модуля; 4 модуля на 100% ниже уровня | CONFIRMED |
| CNT-021 | P2 | 7 из 16 модулей A1 | A1-контент использует Present Continuous / Future Simple, которые вводятся на A2 | CONFIRMED |
| CNT-022 | P2 | все 86 модулей, L3 `collocation_matching` | 1648 из 1684 пар — дословные предложения из `vocabulary`; коллокаций нет | CONFIRMED |
| CNT-023 | P2 | 66 модулей `shadow_reading`, 21 `dictation` | Тексты пересобраны из того же пула предложений — 4 урока модуля это один текст в четырёх обёртках | CONFIRMED |
| CNT-024 | P3 | 31 модуль, `final_test.content.exercises` | 211 мета-упражнений-наполнителей — **не отдаются рендером**, мёртвый контент | CONFIRMED (P1→P3) |
| CNT-025 | P3 | 8 модулей C1, L7 | Один и тот же аналитический абзац повторён 3 раза подряд | CONFIRMED |
| CNT-026 | P3 | 42 модуля | 148 объяснений — заглушка «Перевод фразы из словаря модуля.» | CONFIRMED |
| CNT-027 | P3 | `app/static/audio/lessons_old/` | 946 MB неиспользуемого аудио + 44 iCloud-дубля в деплой-пейлоаде | CONFIRMED |
| CNT-028 | P3 | `daily_lessons` (БД) | 55 из 247 `audio_url` указывают на несуществующий файл | CONFIRMED |
| CNT-029 | P3 | 71 из 548 `listening_quiz` | `transcript` содержит ключ ответа, а не транскрипт; 8 — литералы `True`/`False` | CONFIRMED |
| CNT-030 | P3 | 24 упражнения, L6 `reading` | Токены `words` не собирают `correct` (нет финальной пунктуации) — латентно | CONFIRMED (P1→P3) |
| CNT-031 | P3 | 3 места (`matching`) | Дубли правой стороны → клиентская обратная связь красит верную пару красным | CONFIRMED |
| CNT-032 | P3 | `lessons` (БД) | `title_en` авторится, но теряется при импорте (колонки нет): 517 уроков | CONFIRMED |
| CNT-033 | P3 | 2 юзера / `grammar_topics` / `skip-lesson` | Мелкий долг прогрессии: `onboarding_level='A0'`, дубли грамм-тем между уровнями, hint 1 день из 18 | CONFIRMED |

### P1 — детали

**CNT-001 · `matching` в финальном тесте не засчитывается на пути первой попытки**
Сценарий: ученик открывает финальный тест из плана дня или из каталога, безошибочно составляет все
пары — и получает за этот вопрос 0. Цепочка: `final_test.html:1053-1064` шлёт `answer_<i>` = **строку
для показа** («9 o'clock → AT; Friday → ON») и отдельно `pairs_<i>` = JSON. Обработчик
`render_final_test_lesson` (`app/curriculum/routes/grammar_quiz_lessons.py:591-598`) собирает
**только** ключи `answer_*`; `pairs_<i>` молча отбрасывается. Далее `process_quiz_submission`
(`app/curriculum/grading.py:1157-1192`): `json.loads` строки падает → `raw=None` → не список и не
словарь → фолбэк на `answers['<i>_pairs']`, которого в собранном словаре нет (ключи — int-индексы) →
`user_pairs is None` → `is_correct=False`.

**Поправка скептика (принята, проверена независимо).** Формулировка «всегда, любым путём» —
**опровергнута**: обработчиков финального теста **два**, и второй исправен.
`final_test_lesson` (`:983`, маршрут `/curriculum/lesson/<id>/final_test`) разбирает `pairs_*`
(`:1047-1078`) и переупаковывает их для грейдера. Скептик прогнал оба маршрута реальным POST'ом
того, что шлёт фронт: `/learn/<id>/` → score 50, `passed: false`; `/curriculum/lesson/<id>/final_test`
→ score 100, `passed: true` на одном и том же безошибочном ответе.
**Но все входы первой попытки ведут в сломанный обработчик:** план дня
(`app/daily_plan/items/curriculum.py:280`), каталог (`module_lessons.html:246`) и
`_lesson_completion_url` (`lessons.py:715`) дают `/learn/<id>/`, а `final_test` **не входит** в
`_CANONICAL_LESSON_ROUTE_TYPES` (`app/curriculum/routes/main.py:20-32`), поэтому редиректа на
исправный маршрут нет. Обход существует и достижим: кнопка «Повторить» на странице результатов
(`final_test_results.html:357`) ведёт именно в исправный маршрут — т.е. **первая попытка оценивается
неверно, повторная верно**.
Масштаб: **105 вопросов, 86 из 86 модулей** (1–4 на тест) — число сверено с БД. Максимально
достижимый балл 78.9–96.8% при пороге 75, тест остаётся проходимым. Побочно: занижение score-aware
XP и фантомные строки `QuizErrorLog` (они разрешимы — в `error_review.html:211` есть вид `pairs`).
**Severity: оставлено P1** — определение P1 («работает неверно, но пользователь может достичь цели
другим путём») описывает ровно этот случай. Скептик аргументировал **P2** (ни один урок не
становится непроходимым). Разногласие вынесено на второй проход трёх скептиков в **Task 6**.
**Пересечение с 2026-06-13:** E-033 чинил ровно этот сценарий, но в `process_final_test_submission`,
которая курсовыми финальными тестами **не вызывается** (её путь `/api/lesson/<id>/submit` читает
`content['questions']`, а корпус хранит `test_sections`). Это не регресс, а **незакрытая половина**:
фикс лёг в неиспользуемую ветку. Тестов, проходящих matching через маршрут, нет
(`test_final_test.py` покрывает только rate-limit, `test_final_test_patch.py` — нормализацию).
Помечено для кросс-зонной дедупликации в Task 6 — **первопричина в коде (зона «Разделы»)**: два
разошедшихся обработчика одного экрана.
Фикс скриптом: **нет** — правка кода (читать `pairs_<i>` в `render_final_test_lesson` либо свести
два обработчика в один).

**CNT-002 · `matching` в уроке чтения рендерится как пустое текстовое поле**
Сценарий: ученик открывает L6 (`reading`) одного из 14 модулей, доходит до вопроса
«Соотнесите слова с переводом» — и видит **пустое поле ввода**. Ни одной пары на экране.
`app/templates/curriculum/lessons/text.html:383-441` разбирает `true_false`, `multiple_choice`,
`fill_blank`+options, `ordering`, иначе — текстовый `input`; ветки `matching` нет, `question.pairs`
шаблон не упоминает ни разу. `data-correct` берётся как `question.correct_answer or question.correct`,
а в контенте `"correct": false` → в атрибут попадает строка `False`, т.е. вопрос «проходится»
буквальным вводом `false`.
Масштаб: 14 модулей (A1→C1). Скептик подтвердил рендером реального контента через `/learn/<id>/`:
в HTML есть «Соотнесите», нет ни одной пары, есть
`<input class="answer-input" data-correct="False">`. Сверено с БД: уроки
`240, 276, 474, 564, 726, 744, 798, 1266, 1284, 1320, 1392, 1500, 1518, 1536`. Сервер чтение не
переоценивает (`reading` вне `_SERVER_GRADED_TYPES`, `lessons.py:302-310`) — клиентский балл
принимается как есть.
**Две поправки скептика (приняты).** (1) Потолок 80–86% **обходится**: Jinja печатает `False`
строкой, `checkAnswer` приводит к нижнему регистру — т.е. ввод `false` засчитывается как верный
ответ. На практике недостижимо, но «никогда не превысит» буквально неверно. (2) Существеннее:
на четырёх уроках из пяти вопросов (240, 276, 474, 564) мёртвый вопрос **вдвое срезает бюджет
ошибок** — при пороге 0.6 нужно 3 из 5, поэтому ученик может ошибиться лишь один раз вместо двух,
иначе урок не завершается до переответа.
**Severity: оставлено P1** — на этих четырёх уроках завершение реально блокируется при двух ошибках.
Скептик аргументировал **P2** (в общем случае урок проходится). Разногласие — на второй проход
Task 6.
Фикс скриптом: **да** — конвертировать 14 упражнений в поддерживаемый тип (пары легко разворачиваются
в `multiple_choice`); либо код: ветка `matching` в шаблоне.

**CNT-003 · озвучка слов: 1570 файлов не существует**
Сценарий: ученик открывает любой `vocabulary`- или `flashcards`-урок, жмёт динамик — тишина.
`app/curriculum/routes/vocabulary_lessons.py:154` подставляет `audio_url` из `word.listening`
(заполнено у 19 890 слов), `vocabulary.html:67` рендерит кнопку по факту непустого `audio_url`,
обработчик (`:301`) делает `audioPlayer.play()` **без `.catch()`** → тишина + unhandled rejection.
Проверено независимо: на диске **33** файла `pronunciation_*.mp3`; корпус ссылается на 6158
уникальных аудио, из них **1571 отсутствует, 1570 — `pronunciation_en_*`**. Слов курса затронуто
**1498 из 1580**.
Фикс скриптом: **частично** — сгенерировать 1570 клипов требует внешнего TTS (ручной шаг). Скриптом
делается смягчение: обнулить `listening`/`get_download` там, где файла нет, чтобы кнопка не рисовалась.

**CNT-004 · валидатор не видит 83% аудио-ссылок**
`_iter_audio_refs` (`scripts/validate_module_completed_json.py:286`) обходит только верхний уровень +
`items`/`questions`/`exercises` + `test_sections[].exercises[]`. Рекурсивный обход находит **8274**
аудио-строки (6158 уникальных), обходчик выдаёт **1397**. В слепой зоне — `vocabulary[].audio`,
`cards[].audio`, `sections[].table[].audio`, `text.lines[].audio`, `sections[].rules[].audio`, а также
**список-форма** `audio: [...]`, которую код не разбирает даже на посещаемых путях. Все 1570
отсутствующих файлов CNT-003 лежат ровно в слепой зоне — поэтому отчёт рапортует `missing=0`.
Фикс скриптом: **да** — рекурсивный обход по ключам `audio`/`audio_url` с поддержкой `str | list[str]`;
`scripts/` под гитом, доставляется коммитом.

**CNT-005 · входные модули уровней не защищены — очередь ведёт через уровень**
Сценарий: юзер `onboarding_level='A1'` закрыл A1 M1 и прошёл 10/18 A1 M2 (56%, ниже порога 80%,
открывающего M3). Секция «Дальше по курсу» показывает ему уроки **A2 M1**; `check_module_access`
пропускает (первый модуль уровня — auto-accessible), `check_lesson_access` пропускает (первый урок).
Пройдя A2 M1 целиком, он открывает A2 M2 по правилу «предыдущий на 80%» — и идёт по A2, не тронув
A1 M3–M16 (14 модулей, 252 урока).
`app/curriculum/security.py:280-286` **сам документирует** защиту: «The safeguard against a B1 user
jumping to C2's first module is that higher-level ENTRY modules must carry `Module.prerequisites`».
Проверено запросом: `prerequisites` непусты ровно у **2 модулей из 86** (A1 M4, A1 M12), оба —
внутриуровневые и оба неработающие (CNT-014). **Ни один входной модуль уровня (A2 M1, B1 M1, B2 M1,
C1 M1) не несёт prerequisites** → заявленная защита в данных отсутствует полностью.
Фикс скриптом: **да** — миграция, проставляющая `prerequisites` четырём входным модулям в формате,
который парсер понимает: `[{"type":"module","id":<id>,"min_score":70}]`. Placement не ломается —
`_user_min_level_order` пропускает prereq'ы ниже placement-уровня.

**CNT-006 · 196 примеров лексики с приклеенной фразой-наполнителем**
`"Clickbait headlines distort facts. It appears during focused classroom practice."` —
`example_translation` при этом переводит **только первое предложение**, поэтому карточка выглядит
недопереведённой. 196 вхождений, 33 модуля, всегда `L1.vocabulary[].example`. Строка наследуется
`flashcards.cards[].example` и `collocation_matching.pairs[].phrase` (см. CNT-022), умножая охват.
`validate_corpus.py` ловит `extension/practice term N`, но не эту фразу.
Фикс скриптом: **да** — удалить точную строку.

**CNT-007 · 174 строки чтения с «This reading version adds context one.»**
`module_B2_10_crime_and_law.json` L6, `text.lines[23].text`: `"The crime rate has decreased in our
city. This reading version adds context one."` — русский перевод строки эту часть не содержит.
173 вхождения «…context one.» + 1 «…context two.», 18 модулей, всегда `L6.reading.text.lines[].text`.
Фикс скриптом: **да** — regex-удаление.

**CNT-008 · пять аудиофайлов делят два модуля с разными правильными ответами**
`A2M22L6_ex1..4.mp3` и `A2M19L12_listen_1.mp3` адресуются из двух модулей сразу.
`module_A2_22_holidays_traditions.json` L8 ждёт «New Year» / «Many gifts» / «Last night», а
`module_A2_7_healthy_lifestyle.json` L8 — «You should work out every day.» / «I go to the gym.» /
«8 hours» **по тем же четырём файлам**. Владелец определён по префиксам: A2_22 использует `A2M22`
единообразно (19 ссылок), у A2_7 — 14 ссылок `A2M7`/`A2M07` и 4 чужих `A2M22`. Значит сломан **A2_7
L8: 4 вопроса из 6** звучат не про то. Аналогично `A2_4` L18 (1 ссылка из 19) против `A2_19`.
Урок остаётся завершаемым (`listening_quiz` не входит в `_SCORE_BASED_LESSON_TYPES`, а варианты
ответов текстовые и угадываются), поэтому P1, не P0.
Фикс скриптом: **частично** — перенаправить ссылки скриптом можно, но 4 клипа для A2_7 надо
сгенерировать заново (внешний TTS).

**CNT-009 · mail-merge-диалоги учат неграмотному английскому**
Слот подставляется из словаря модуля без проверки части речи, и результат объявлен **правильным
ответом**:
- `module_A1_4_objects_around_us.json` L12 ex[8]: «Do you have a brown?» → `correct: "Yes, I have a brown."`
- `module_B1_1_past_irregular.json` L12 ex[7]: «Tell me about your tell — told.» → `correct: "My tell — told is special to me."` (в слот попала пара неправильного глагола)
- `module_B1_8_money_and_finances.json` L12 ex[8]: «What is your favorite debt?» → `correct: "My favorite debt is the new one."`
Измерено собственной регуляркой по 9 фиксированным фреймам: **110 из 843 упражнений (13%) в 55
модулях**. Это **нижняя граница** — финдер с 19 фреймами насчитал ≥226 (27%); разница не
верифицирована и в число не берётся.
Фикс скриптом: **частично** — удалить заведомо сломанные (фрейм + блоклист по части речи) скриптом
можно; писать замену — авторская работа.

### P2 — детали (кратко)

- **CNT-010** — `target_phrases: ["This is","That is","I have","I like"]` + A1-шаблон
  `"This is ___. That is ___."` стоят на **32** `writing_prompt` (13 A1 + **19 A2**) с посторонним
  заданием («Describe your plans for next week… Use 'going to'»). `lessons.py:1775` делает
  `target_phrases_required = bool(target_phrases and mode=='guided')` → завершение блокируется, пока
  в тексте нет **хотя бы одной** из четырёх фраз. Уточнение к исходной претензии: требуется одна из
  четырёх, а не все, поэтому естественный ответ часто проходит случайно («I like…») — отсюда P2, а
  не P1. Экранный `template` при этом прямо противоречит заданию. Фикс скриптом: **да** (очистить
  `template`/`target_phrases`/`hint_words` на 19 A2-уроках).
- **CNT-011** — `python scripts/validate_corpus.py` (запуск из README-стиля, без `PYTHONPATH`) не
  импортирует `app` (`sys.path[0]` = `scripts/`), печатает одну строку-примечание и **пропускает
  рантайм-схему**, после чего всё равно выводит `✅ PASS — ready to import`. Гейт, обещающий
  «rejects exactly what the admin re-import would reject», при штатном вызове ничего не проверяет.
  Фикс скриптом: **да** (вставить корень проекта в `sys.path`; при недоступности схемы — не PASS).
- **CNT-012** — 29 «блокирующих» `empty-required-field` на `sentence_completion` — ложные:
  пустой `prompt` легален, когда пропуск в начале предложения (`context` + `prompt_after` несут текст,
  `sentence_completion.html:39-56` так и рендерит). Затронуты 6 модулей (B2_12, C1_11, C1_1, C1_4,
  C1_5, C1_7). С `--strict` валидатор заблокировал бы корректный реимпорт. Фикс скриптом: **да**.
- **CNT-013** — `diff_module_json_against_db.py` при любом запуске без `--no-db` печатает «could not
  connect to DB» и выходит с кодом 2: `_try_get_db_session` зовёт `create_app(os.environ.get("FLASK_ENV",
  "development"))`, а `create_app(config_class=Config)` передаёт аргумент в `app.config.from_object`,
  который на строке делает `import_string('development')`. Второй дефект в той же функции —
  `from extensions import db` (корневой `extensions.py`), тогда как приложение использует
  `app.utils.db.db`: даже при исправленном `create_app` получаем `RuntimeError: The current Flask app
  is not registered with this 'SQLAlchemy' instance`. Тот же сломанный хелпер — в
  `audit_module_completed_json_gaps.py`. Отчёт в таблице выше получен обходом обоих дефектов.
  Фикс скриптом: **да**.
- **CNT-014** — `modules.prerequisites` у A1 M4 = `["module_1","module_2","module_3"]`, у A1 M12 =
  `["module_10","module_11"]`. `Module.check_prerequisites` (`app/curriculum/models.py:105-113`)
  оставляет только элементы `isinstance(p, dict) and p['type']=='module'` → список пуст →
  `return True, []`. Оба авторских чекпоинта — тихие no-op'ы; в `find_next_lesson_linear`, который
  гейтит **только** через `check_prerequisites`, prerequisite-гейтинга нет во всём каталоге.
  Слаги уровне-относительные (`module_10`), нужен конвертер в `modules.id`, а не только смена формы.
- **CNT-015** — `duration_seconds` отсутствует у **86/86** `audio_fill_blank` и `shadow_reading`,
  равен `0` у 24 уроков (12 `listening_immersion` + 12 `dictation`). `app/api/daily_plan.py:176`
  берёт `int(float(content.get('duration_seconds') or 300))` — и `None`, и `0` дают 300 с при
  реальных ~52 с. Один `audio_fill_blank` закрывает половину 10-минутной цели слушания (всю — с
  повтором). Фикс скриптом: **да** (ffprobe + запись реальных длительностей).
- **CNT-016** — собственный gap-аудитор проекта считает каноническими **1 модуль из 86**; остальные
  85 — из-за отсутствующего `sentence_correction`, который контракт (§4) требует в каждом модуле
  (исключение прописано только для A1 M1). Тип полностью реализован — маршрут, шаблон,
  `grade_sentence_correction_multi`, запись в `_SCORE_BASED_LESSON_TYPES` — но из курса недостижим.
- **CNT-017** — `word_collocations` и `cultural_notes` содержат **0 строк** при том, что
  `vocabulary_lessons.py:139-145` делает по два `IN(...)`-запроса на каждый рендер урока. Фича
  «collocation pills», описанная в `CLAUDE.md`, не отрисовывается ни разу.
- **CNT-018** — `ipa_transcription` / `synonyms` / `antonyms` / `frequency_band` / `etymology`
  заполнены ровно у **4943 из 25 089** строк (19.7%) — одинаковое число во всех пяти колонках, т.е.
  один backfill остановился. На словах курса — 888 из 1580 (56.2%): соседние карточки в одном уроке
  выглядят по-разному (у одной есть IPA и бейдж частотности, у другой нет).
- **CNT-019** — `antonyms::text = '["null"]'` в **1728** строках, `synonyms` — в **180**. UI спасает
  `_clean_word_list`, но любой другой потребитель отрисует «Антонимы: null», а метрика покрытия
  CNT-018 завышена примерно вдвое. Прочие мусорные формы (`"-"`, `"n/a"`, `[]`) в данных **не
  встречаются** — защита написана шире, чем реальная грязь. Фикс скриптом: **да** (один UPDATE).
- **CNT-020** — по тегам `collection_words.level`: **4 модуля на 100% ниже своего уровня**
  (B1 M1, A2 M1, A2 M10, A2 M23 — все 20/20 слов A1), ещё 9 — на 40–60% (B1 M16/M17, B2 M10, C1 M9…);
  в обратную сторону A1 M11 «Профессии» содержит 15% слов B1/B2. `frequency_rank` для перекрёстной
  проверки непригоден (0 у большинства слов курса).
- **CNT-021** — регекс-скан контента A1 против A1-силлабуса: Present Continuous встречается в **7 из
  16** модулей A1 (в т.ч. в самом грамматическом уроке A1 M3 — `is wearing`, при том что тема
  вводится на A2 M15), Future Simple — в 2 (A1 M9 L4 grammar и L6 reading: `will rain`, `will snow`).
  Обратная проверка A1+A2 на структуры B2/C1 почти чиста — одно попадание.
- **CNT-022** — **1648 из 1684** пар `collocation_matching` (98%, все 86 модулей) — дословные
  предложения из `vocabulary`/`flashcards`, а не коллокации. Единственный написанный вручную модуль
  (A1 M1: «Nice to meet you.») показывает, как задумывалось. Урок 3 каждого модуля — повтор урока 1,
  занимающий слот плана и начисляющий XP.
- **CNT-023** — `shadow_reading.text` на ≥90% состоит из тех же предложений в **66 модулях**,
  `dictation.transcript` — в 21. Внутримодульных near-dup пар (Jaccard ≥0.35) — 72. Кросс-модульных
  дублей длинной прозы — **0** (пред. проход де-рециклинга сработал между модулями, но не внутри).

### P3 — детали (кратко)

- **CNT-024** (понижено P1→P3) — 211 мета-упражнений-наполнителей («Which option matches the …
  practice focus two?») в 31 модуле лежат в **плоском `final_test.content.exercises`**. Финдер оценил
  это как «40% теста сдаётся без знания английского». **Проверено — не сдаётся:**
  `render_final_test_lesson` (`grammar_quiz_lessons.py:551-557` и `:602-608`) читает плоский
  `exercises` **только если `test_sections` пуст**, а он непуст у всех 86. Прогон реального
  `LessonContentValidator` на C1 M10: `test_sections` → 25 вопросов отдаются, 20 наполнителей в
  плоском хвосте — нет. Это мёртвый контент (и источник расхождения `exercises` в CNT-000), а не дыра
  в оценивании.
- **CNT-025** — в 8 модулях C1 `listening_immersion.text` заканчивается одним и тем же 60-словным
  аналитическим абзацем, повторённым **три раза подряд**; он же — в 8 разных модулях.
- **CNT-026** — 148 объяснений «Перевод фразы из словаря модуля.» в 42 модулях; плюс шапка
  «Дополнительные примеры со словарём модуля» в 73 модулях и `summary.note`-заглушка в 58.
- **CNT-027** — `app/static/audio/lessons_old/` — **946 MB**, ноль ссылок в репозитории и БД
  (`grep -rl lessons_old app/` → пусто); плюс 44 iCloud-дубля вида `A1M1L5_line_1 2.mp3` и 4
  `.DS_Store`. Около половины аудио-дерева уезжает в каждый `docker compose build`.
- **CNT-028** — 55 из 247 строк `daily_lessons.audio_url` указывают на несуществующий файл
  (напр. `id=975`, `audio/lessons/course_1_ch4_lesson1.mp3`). Плеер book-course урока не загрузится.
- **CNT-029** — `transcript` = копия `correct` вместо транскрипта в **71 из 548** `listening_quiz`
  (`module_A1_12_daily_habits.json` L8 ex1: `transcript: "usually"` при `audio_text: "I usually drink
  tea in the morning"`); 8 упражнений содержат `audio_text` = `"True"`/`"False"`, 5 — ни одного поля.
  Сегодня инертно (`quiz.html` рендерит только `question.audio`), но ломает любой будущий
  TTS-реген или «показать транскрипт».
- **CNT-030** (понижено P1→P3) — в 24 `ordering`-упражнениях L6 набор `words` не собирает `correct`
  (нет финальной точки: `['He','goes','to','school','by','bus']` против `'He goes to school by bus.'`).
  Серверный `normalize_sentence` трейлинг-пунктуацию не снимает — но урок чтения **оценивается на
  клиенте**, а `text.html:938` нормализует через `replace(/[^\w\s]/g,'')`, снося всю пунктуацию.
  Сейчас безвредно; станет непроходимым в тот момент, когда чтение переведут на серверный грейдинг.
  Проверено полным перебором перестановок: непроходимых при серверном правиле — 24 из 1078; в
  `ordering_quiz` (1032 упражнения) — **0**, т.е. прошлый `fix_ordering_tokens.py` закрыл свой тип
  и не тронул `reading`.
- **CNT-031** — 3 `matching` с дублями правой стороны (`A1_8` L18 «AT» дважды, `B1_2` L6 «фильм»
  дважды, `B2_7` L18 «+ gerund» дважды). `checkMatch` (`final_test.html:531`) сравнивает **индексы
  пар**, а не значения, поэтому семантически верное сопоставление красится как неверное; серверный
  грейдер при этом сравнивает строки и засчитывает — расходится только визуальная обратная связь.
- **CNT-032** — `lessons` не имеет колонки `title_en`, и `content.title_en` нет ни у одной из 1548
  строк: **517 уроков** теряют авторский английский заголовок при импорте, у 1031 его нет в источнике.
- **CNT-033** — сборная мелочь прогрессии: 2 юзера с `onboarding_level='A0'` (кода нет в `CEFRLevel`,
  спасает `max(order,0)`); `grammar_topics` дублирует тему между уровнями (`a2-23`/`b1-1` Past Simple
  irregular, `b1-17`/`b2-11` Past Perfect) — grammar-SRS считает их независимыми и удваивает
  повторения; `weak_topic_hint` достижим 1 день из 18, потому что `grammar_topic_id` несут только 86
  грамматических уроков, а `CLAUDE.md` описывает несуществующее поле `Module.grammar_topic_id`;
  `check_prerequisites` fail-open на нераспознанной форме и на prereq'е, указывающем на удалённый
  модуль; `POST /api/daily-plan/skip-lesson` возвращает `next_lesson_id`, который `check_lesson_access`
  затем 403'ит (эндпоинт мёртв — 0 ссылок в JS/шаблонах, `lesson_skips` пуст).

### Выразим ли фикс скриптом (обязательная колонка Task 3)

Корпус gitignored → правки контента доставляются **только** скриптом в `scripts/` (он под гитом).
Правки БД — миграцией или скриптом; правки кода — обычным коммитом.

| Носитель фикса | ID |
|---|---|
| **Скрипт по корпусу** (`scripts/*.py` правит JSON) | CNT-002, CNT-006, CNT-007, CNT-010, CNT-024, CNT-025, CNT-026, CNT-029, CNT-030 |
| **Скрипт/миграция по БД** | CNT-005, CNT-014, CNT-019, CNT-028, CNT-033 (часть: `A0`) |
| **Правка кода** (коммит) | CNT-001, CNT-004, CNT-011, CNT-012, CNT-013, CNT-031, CNT-033 (часть: fail-open, skip-lesson, hint) |
| **Скрипт + внешний TTS** (ручной шаг) | CNT-003, CNT-008, CNT-015 |
| **Скрипт + авторская работа** | CNT-009, CNT-016, CNT-017, CNT-018, CNT-020, CNT-021, CNT-022, CNT-023, CNT-032 |
| **Только уборка файлов** | CNT-027 |

**Важное следствие для Task 8–9.** Правки корпуса **не попадают в другие checkout'ы гитом** —
доставляется только скрипт; применить его к своей копии `module_completed/fixed/` обязан каждый, кто
собирается импортировать модули. После любой правки корпуса — повторный прогон
`PYTHONPATH=. python scripts/validate_corpus.py` (0 errors) и **реимпорт через админку**, иначе
правка живёт в JSON, но не в БД (сейчас дрейф нулевой — см. CNT-000, и это состояние нужно
удержать).

### Опровергнуто при проверке — не переоткрывать без новых фактов

- **«40% финального теста сдаётся наугад»** — опровергнуто механикой рендера, см. CNT-024.
- **«24 ordering-упражнения непроходимы»** — опровергнуто клиентской нормализацией, см. CNT-030.
- **«`validate_module_completed_json.py` не гейтит, выходя с кодом 0 при 29 ошибках»** — опровергнуто:
  выход 0 без `--strict` задокументирован (`:50-51`) и является заявленным поведением. Живой остаток
  претензии — ложность самих 29 ошибок (CNT-012).
- **«Тип уроков расходится между источником и БД (`flashcards` vs `card`)»** — опровергнуто:
  расхождение равномерно для всех 172 уроков и оба алиаса обрабатываются кодом (см. CNT-000).
  Первичная выборка показывала только C1-модули из-за усечения вывода, а не из-за выборочности.
- **`dictation`: «gap_text без пропусков» (86/86)** — опровергнуто: маркеры пропусков имеют вид
  `{0}`, а не `_`; проверка искала не тот символ. Реальная сверка `gap_text.format(*answers) ==
  transcript` проходит во всех 86.
- **«Дубли вариантов в MC»** — опровергнуто: «Our dog's» vs «Our dogs» и «Mary's cat» vs «Marys cat»
  различимы грейдером (он не снимает пунктуацию на MC-пути) и являются намеренными дистракторами на
  апостроф.
- **`final_test.passing_score = 75` вместо 70** — не находка: `get_lesson_passing_score`
  (`app/curriculum/constants.py:23-48`) намеренно уважает override из контента.
- **`total_points: 100`** — не находка: поле не читается ни одним грейдером (балл считается как
  доля верных вопросов).

---

## Зона Разделы

> **Task 4** — закрыт. Инвентаризация `url_map` (**531 правило**, 52 blueprint-неймспейса) +
> пять линз. Записано **8 находок** `SEC-001…SEC-008`. Каждая указывает blueprint и конкретный
> сценарий отказа. Пересечений-**регрессов** с реестром `2026-06-13-100-edge-cases.md` — **0**
> (разбор ниже, секция «Сверка с реестром 2026-06-13»).

**Сводка зоны:** P0 — 0 · P1 — 3 · P2 — 0 · P3 — 5.

### Инвентаризация `url_map` (checkbox 1)

Снято из живого `create_app()` (SQLite-конфиг, `TESTING`), сериализовано в `endpoint / rule /
methods / args / defaults`. **531 правило**, из них **240 мутирующих** (POST/PUT/PATCH/DELETE).

| Blueprint | Правил | | Blueprint | Правил | | Blueprint | Правил |
|---|---|---|---|---|---|---|---|
| `admin` | 81 | | `books_api` | 11 | | `curriculum_api` | 6 |
| `study` | 64 | | `user_admin` | 11 | | `learn` | 6 |
| `curriculum_lessons` | 32 | | `api_topics_collections` | 10 | | `seo` / `seo_admin` | 6 / 6 |
| `grammar_lab` | 24 | | `audio_admin` / `book_admin` | 10 / 10 | | `collection_admin` | 5 |
| `books` | 19 | | `curriculum_admin` / `word_admin` | 10 / 10 | | `feedback_admin` | 5 |
| `book_courses` | 18 | | `feedback` | 9 | | `modules` | 5 |
| `api_daily_plan` | 16 | | `topic_admin` | 8 | | `word_contrast_admin` | 5 |
| `auth` | 14 | | `api_words` / `srs_api` | 7 / 7 | | `notifications` | 4 |
| `words` | 14 | | `system_admin` | 7 | | `onboarding` / `reminders` | 4 / 4 |
| `<без blueprint>` | 14 | | `telegram_channel_admin` | 7 | | `telegram` | 4 |
| `api_books` | 13 | | `admin_curriculum` | 6 | | остальные 22 | ≤3 каждый |

**Сверка `url_for` со снимком.** Извлечено **1 118** вызовов `url_for(...)` из `app/**` (`.py`,
`.html`, `.js`); каждый сопоставлен с эндпоинтом и его обязательными аргументами.

- **Несуществующие эндпоинты — 7** (все подтверждены живым `BuildError` в `test_request_context`):
  `study.deck_detail`, `admin.add_book`, `curriculum.lesson_by_id`, `admin.create_course_module`,
  `admin.edit_course_module`, `admin.delete_course_module`, `admin.book_course_enrollments`.
  → `SEC-003`, `SEC-004`, `SEC-005`, `SEC-008`.
- **`url_for` с неверными аргументами — 0.** Первый прогон дал 9 кандидатов; все 9 — артефакт
  однострочного regex'а на многострочных вызовах (обрезался хвост `)`), при чтении исходников оба
  аргумента передаются. Опровергнуто, см. `R2`.
- **Недостижимые роуты — не заявлены.** Попытка вывести «мёртвые роуты» из отсутствия `url_for` +
  отсутствия литерального пути провалилась: `url_prefix` задаётся при регистрации, поэтому полного
  пути (`/api/daily-plan/skip-lesson`) нет в исходниках **даже у самого определения роута**, а
  фронт собирает часть URL динамически. Оба варианта эвристики (по полному пути и по хвосту из двух
  сегментов) давали ложные нули на заведомо живых эндпоинтах. Метод отброшен как ненадёжный;
  претензий на мёртвые роуты в реестре **нет** (см. «Покрытие»).

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. |
|---|---|---|---|---|
| SEC-001 | P1 | `app/api/books.py:685` | `/api/tasks/<id>` и `/api/blocks/<id>` отдают материалы `companion_only` книг мимо `can_user_access_book` | CONFIRMED |
| SEC-002 | P1 | `app/books/routes.py:418` | `?from=` подставляется в `href` кнопки «Назад» ридера без валидации | CONFIRMED |
| SEC-003 | P1 | `app/templates/components/_flashcard_session.html:115` | Колода без карточек на сегодня → `BuildError` → 500 вместо пустого состояния | CONFIRMED |
| SEC-004 | P3 | `app/books/routes.py:63` | `/books/add` отдаёт 500: редирект на несуществующий `admin.add_book` | CONFIRMED |
| SEC-005 | P3 | `app/curriculum/routes/grammar_quiz_lessons.py:590` | Ветка «попытки исчерпаны» без XHR-заголовка ведёт в несуществующий `curriculum.lesson_by_id` | CONFIRMED |
| SEC-006 | P3 | `app/api/books.py:643` | `/api/book/<id>/content` отдаёт захардкоженную заглушку как боевой ответ | CONFIRMED |
| SEC-007 | P3 | `app/curriculum/routes/srs_api.py:39` | 240 ad-hoc `jsonify({'error': …})` вместо `api_error` — форма JSON-ошибки расходится по кодовой базе | CONFIRMED |
| SEC-008 | P3 | `app/templates/admin/book_courses/create_module.html:20` | 3 шаблона-сироты с 3 несуществующими эндпоинтами | CONFIRMED |

### P1 — детали

**SEC-001 · `app/api/books.py:685`, `:716`, `:753` · blueprint `api_books` · обход `can_user_access_book`**

Три эндпоинта под `@api_auth_required` и **без единой проверки доступа к книге**:

| Роут | Что отдаёт | `can_user_access_book` | `_draft_hidden` |
|---|---|---|---|
| `GET /api/tasks/<int:task_id>` | `task.payload` целиком | ❌ | ❌ |
| `GET /api/blocks/<int:block_id>/tasks` | список задач блока | ❌ | ❌ |
| `GET /api/blocks/<int:block_id>` | `grammar_key`, `focus_vocab`, типы задач | ❌ | ❌ |

Соседи по тому же файлу — `/books/<id>` (`:53`), `/books/<slug>/chapters` (`:143`),
`/books/<id>/chapters` (`:159`), `/books/<id>/chapters/<n>` (`:175`), `/chapters/<id>` (`:789`) —
зовут **оба** гейта. То есть это пропуск, а не осознанная модель.

Сценарий отказа (проверено на `learn_db_prod`): в базе **11 книг, все `rights_status =
companion_only`** (публичных нет ни одной), под ними **84 `block`** и **1 803 `task`**. Модуль
`books` выдан **20 из 45** пользователей. Любой из оставшихся **25** аутентифицированных
пользователей — который на `/books`, `/read` и `/api/books/*` получает пустой каталог и 403 —
перебирает `GET /api/tasks/1…1803` и выкачивает весь производный учебный материал по всем
companion-книгам: у `reading_mcq` это `intro/title/questions/objectives/result_bands`, у
`final_test` — `sections/pass_score/total_questions` (то есть задания вместе с ключами), у
`vocabulary` — `phrases/match_phrase_to_meaning/complete_the_sentence`. `api_auth_required` —
это только «аутентифицирован», ни модуля, ни прав книги он не смотрит
(`app/api/decorators.py:16-63`). Токен JWT работает так же, как cookie-сессия.

Верификация: перечитаны все 13 роутов `api_books` (AST-проход + чтение тел), `app/api/decorators.py`,
`app/books/access.py`; blueprint регистрируется в `app/__init__.py:205` без `before_request`;
счётчики и `rights_status` сняты запросами к `learn_db_prod`.
⚠️ По продуктовым критериям реестра это P1 (учебный контент, не персональные данные пользователя).
По лицензионной линзе это самая дорогая находка зоны: гейт `companion_only` существует именно
затем, чтобы этот материал не покидал круг обладателей модуля.

**SEC-002 · `app/books/routes.py:418` и `:1187` · blueprint `books` · `?from=` уходит в `href` без валидации**

```python
back_url = request.args.get('from')
if back_url in ('daily_plan', 'linear_plan'):
    back_url = None            # это трекинг-флаг, а не URL
```
Всё, что не совпало с двумя литералами, уходит в шаблон как есть и рендерится в **три** ссылки
`reader_simple.html:19`, `:129`, `:242`. На `:1187` (вторая ветка того же роута) нет даже отсева
двух литералов.

Сценарий отказа: жертве присылают `/books/7/read?from=https://evil.example/login`. Страница
открывается нормально, читатель жмёт «Назад» — и уходит на подставной домен уже в контексте
доверенной ссылки. Вариант `?from=javascript:…` даёт клик-XSS в аутентифицированном контексте;
сработает ли он — зависит от того, как браузер трактует `script-src 'unsafe-inline'` рядом с nonce
в CSP3 (`app/middleware/security.py:74,91`), **в браузере это не проверялось** — открытый редирект
воспроизводится без оговорок, `javascript:`-вариант заявлен как требующий проверки.
Третья ветка (`:428`): при `Referer`, содержащем подстроку `curriculum` или `module`, реферер
подставляется в `back_url` целиком — то есть внешний `https://evil.example/curriculum` тоже
становится целью кнопки «Назад».

Контраст: в проекте есть `get_safe_redirect_url(next_url, fallback)` (`app/auth/routes.py:66`),
сверяющий netloc с `request.host`; он зовётся в `app/__init__.py:317`, `words/routes.py:1649`,
`curriculum/middleware.py:144`, `curriculum/routes/admin.py:461,475`, `grammar_lab/routes.py:147,177`,
`reminders/routes.py:745`, `onboarding/routes.py`. Ридер — единственное место, где параметр
навигации минует этот хелпер.

**SEC-003 · `app/templates/components/_flashcard_session.html:115` · blueprint `study` · 500 на пустой колоде**

`url_for('study.deck_detail', deck_id=fc_deck_id)` — эндпоинта `study.deck_detail` в `url_map`
нет; существуют `study.deck_settings` (`/study/my-decks/<id>/settings`) и `study.cards_deck`
(`/study/cards/deck/<id>`).

Сценарий отказа: пользователь открыл `/study/cards/deck/<id>` для колоды, в которой слова есть
(иначе роут отдал бы редирект ещё на `app/study/routes.py:522-525`), но на сегодня всё повторено
либо выбран дневной лимит новых. `SRSService.get_card_counts` возвращает
`nothing_to_study = due_count == 0 and (new_count == 0 or not can_study_new)`
(`app/study/services/srs_service.py:529`); роут рендерит `study/cards.html` с
`fc_nothing_to_study=True` **и** `fc_deck_id=deck_id` (`routes.py:559,565`). Шаблон входит в
`{% if fc_nothing_to_study %}` (строка 74), доходит до строки 115 и получает `BuildError`.
Вместо экрана «Сейчас нечего учить!» пользователь видит 500 — то есть страница ломается ровно
в тот момент, когда должна была похвалить за выполненную работу. Возвращается при каждом заходе,
пока не наступит срок следующего повторения.

Верификация: `url_for('study.deck_detail', deck_id=1)` в `test_request_context` →
`BuildError: Could not build url for endpoint 'study.deck_detail'`; `study.cards_deck` и
`study.deck_settings` из того же прогона строятся успешно. `fc_deck_id` задаётся ровно в одном
месте — `app/study/routes.py:565`; на `:501` (`/study/cards`) он `None`, поэтому ветка молчит и
дефект не виден на основном экране карточек.

### P3 — детали

**SEC-004 · `app/books/routes.py:63`** — `add_book_redirect` (`GET|POST /books/add`,
`@login_required @admin_required`) делает `redirect(url_for('admin.add_book'))`. Такого эндпоинта
нет — правильный `book_admin.add_book` (`/admin/books/add`). Админ, зашедший по легаси-URL, вместо
flash + редиректа получает `BuildError` → 500. P3, а не выше: ссылок на `/books/add` в шаблонах
и JS нет (grep — 0), роут достижим только вводом URL вручную или по старой закладке.

**SEC-005 · `app/curriculum/routes/grammar_quiz_lessons.py:590`** — в `render_final_test_lesson`
ветка «попытки финального теста исчерпаны» для не-XHR запроса делает
`redirect(url_for('curriculum.lesson_by_id', lesson_id=...))`. Эндпоинт живёт в blueprint `learn`
(`learn.lesson_by_id`, `app/curriculum/routes/main.py:500`), в `curriculum` его нет →
`BuildError` → 500 вместо flash + возврата к уроку. Путь **живой, но сегодня недостижим**:
`final_test` не входит в `_CANONICAL_LESSON_ROUTE_TYPES` (`main.py:20-32`), поэтому
`/learn/<id>/` действительно рендерит этот хендлер, однако единственный отправитель формы —
`final_test.html:1069-1071` — шлёт `fetch(window.location.href)` с
`X-Requested-With: XMLHttpRequest`, и срабатывает XHR-ветка (`429` JSON). `<form>` в шаблоне не
осталось (grep — 0). Дефект вскроется, как только POST придёт без заголовка: клиент без JS,
прокси, срезающий кастомные заголовки, или будущая правка фронта.

**SEC-006 · `app/api/books.py:643`** — `GET /api/book/<int:book_id>/content` под
`@api_auth_required` возвращает `content_html: '<p>Sample book content would go here...</p>'`,
словарные подсказки `marlin`/`struggle` и вопрос про Сантьяго — захардкоженный `mock_content`
с комментарием «In a real implementation…». Роут зарегистрирован, отвечает `200 {'success': True}`,
проверок доступа к книге не делает (входит в перечень `SEC-001`, но самостоятельного вреда
не несёт — данных из БД не отдаёт вовсе). Потребителей не найдено. Это прототип, оставшийся
боевым роутом: любой клиент, написанный по `url_map`, получит правдоподобный успешный ответ
с выдуманным содержимым.

**SEC-007 · `app/curriculum/routes/srs_api.py:39` (и ещё 239 мест в 32 файлах)** — конвенция
проекта: `api_error(code, message, status)` (`app/api/errors.py`), дающий
`{'success': False, 'error': '<slug>', 'message': '<текст>', 'status': <int>}` — та же форма, что
у глобальных `handle_403/404/500_error` (`app/__init__.py`). Фактически в кодовой базе **240**
ad-hoc `jsonify({'error': …})`: `app/admin/book_courses.py` — 29, `book_courses_api.py` — 27,
`srs_api.py` — 20, `admin/routes/book_routes.py` и `audio_routes.py` — по 15,
`curriculum/routes/lessons.py` — 12, далее длинный хвост. У них нет ни `success`, ни `message`, а
`error` содержит **английское предложение** (`'Internal server error'`, `'lesson_id parameter
required'`, `'User not enrolled in this course'`) вместо slug'а. Фронт при этом читает
`data.message` в **102** местах и `data.error` в **284**: `flashcard-session.js:1131,1282`,
`linear-daily-plan.js:224`, `quiz-deck-editor.js:225,343,424`, `study/deck_edit.html:550,952,1053`,
`curriculum/lessons/quiz.html:1601` и т. д. — то есть при ошибке от «ad-hoc»-эндпоинта тост
показывает захардкоженный fallback («Ошибка при сохранении») вместо серверной причины, а код
ошибки нельзя разобрать программно. P3: пользователь цели достигает, теряется только точность
диагностики; правка — механическая, но широкая, поэтому в Task 9 берётся не целиком.

**SEC-008 · `app/templates/admin/book_courses/{create_module,edit_module,index}.html`** — три
шаблона, которые не рендерит ни один роут (grep по `render_template` — 0 вхождений), и внутри них
`url_for` на три несуществующих эндпоинта: `admin.create_course_module` (`create_module.html:20`),
`admin.edit_course_module` (`edit_module.html:20`), `admin.delete_course_module`
(`edit_module.html:148`), `admin.book_course_enrollments` (`index.html:150`). Все четыре дают
`BuildError` в живом `test_request_context`. Поскольку шаблоны-сироты, 500 никогда не наступает —
дефект в том, что мёртвые файлы держат ссылки на давно переименованный API и при попытке их
«оживить» страница сразу упадёт. Зона первопричины — Разделы (несуществующие эндпоинты);
файлы лежат в админской подпапке, поэтому **Task 5** отдельно проверил, не является ли какая-то
из этих страниц потерянной, а не мёртвой. **Ответ (Task 5, `RA5`): все три мёртвые** — роутов
CRUD модулей книжного курса не существует вовсе (модули только генерируются),
а `index.html` вытеснен `list.html`.

### Сверка с реестром `2026-06-13-100-edge-cases.md` (checkbox 5)

Все 102 находки того реестра закрыты; проверено, не переоткрылась ли какая-то. **Регрессов — 0.**

| Находка Task 4 | Смежная закрытая находка 2026-06-13 | Регресс? |
|---|---|---|
| `SEC-001` | `E-047` (`allowed_text_percent` не применялся при выдаче текста), `E-048` (`audio_rights_status` не проверялся), `E-050` (аноним в `accessible_books_filter`) | **Нет.** E-047 закрыт и в дереве работает: `app/books/routes.py:434` усекает текст с явной ссылкой на аудит. `SEC-001` — другой роут-семейство (`/api/tasks`, `/api/blocks`), которое ни одна из трёх находок не покрывала: там гейт не «сломан», его никогда не было |
| `SEC-002` | — | **Нет.** В реестре 2026-06-13 нет находок про `?from=`/`back_url`/open-redirect (grep по файлу — 0) |
| `SEC-003`, `SEC-004`, `SEC-005`, `SEC-008` | — | **Нет.** Класс «`url_for` на несуществующий эндпоинт» в 2026-06-13 не разбирался |
| `SEC-006`, `SEC-007` | — | **Нет** |

Отдельно проверено, что **не** переоткрылось: `E-078` (rollback в `admin_audit_required` при
провале аудит-коммита) — на месте, `app/admin/utils/decorators.py:111-119`.

### Опровергнуто при проверке — не переоткрывать без новых фактов

| # | Претензия | Почему опровергнуто |
|---|---|---|
| R1 | 4 мутирующих роута в `app/admin/routes/word_contrast_routes.py` (`create`/`update`/`delete`/`import`) не имеют ни `@login_required`, ни `@admin_required` — только `admin_audit_required` | `admin_audit_required` **сам возвращает** `admin_required(wrapped_view)` (`app/admin/utils/decorators.py:122`), а `admin_required` — `login_required(wrapped_view)` (`:62`). Гейт на месте; ложное срабатывание детектора «по списку декораторов» |
| R2 | 9 вызовов `url_for` с недостающими обязательными аргументами (`words.public_contrast`, `learn.learn_by_module` ×7) | Артефакт regex'а: тело `[^)]*` обрывалось на первой `)` многострочного вызова. Прочитаны все 9 (`words/routes.py:343,351`, `curriculum/security.py:389`, `routes/test_out.py:36`, `routes/lessons.py:1479,1926,2066`, `routes/card_lessons.py:469,673`) — оба аргумента передаются |
| R3 | `app/templates/admin/components.html:141,200,299` ссылается на несуществующие `admin.edit`, `admin.delete_user`, `admin.list` | Все три — внутри Jinja-комментариев `{# Usage: … #}`, документирующих макросы. Кодом не исполняются |
| R4 | `GET /covers/<filename>` (`app/uploads/routes.py:28`) — path traversal | `secure_filename` + жёсткая сверка `safe_filename != filename` → 404, затем `os.path.isfile`, затем whitelist MIME с принудительным `image/jpeg`. Обхода не построено |
| R5 | 28 роутов с path-id и без `current_user.id` в теле — потенциальные IDOR | Прочитаны все: публичные витрины (`/u/<username>`, `/contrast/<a>/<b>`, `/og/*`, `/quiz/shared/<code>`), токен-пути (`/reset_password/<token>`, `/o/<token>.gif`), каталожные справочники (`/api/words/<id>`, `/api/topics/<id>`) и уроки под `@require_lesson_access`. Ни одного пути к чужим пользовательским данным |
| R6 | Отсутствие savepoint вокруг XP в `card_lessons.py:867`, `study/api_routes.py:868`, `books/api.py:1110,1300` (конвенция CLAUDE.md) | Во всех четырёх `db.session.commit()` находится **внутри того же `try`**, что и начисление, а предшествующая запись (`LessonAttempt`/прогресс) закоммичена раньше отдельным блоком. `rollback()` в `except` откатывает только незакоммиченную XP-работу — ровно тот инвариант, который savepoint и обеспечивает. Правки не требуется |
| R7 | «Мёртвые роуты»: 93 эндпоинта без `url_for` и без литерального пути в исходниках | Метод отброшен (см. «Инвентаризация»): `url_prefix` навешивается при регистрации, поэтому полный путь отсутствует даже у определения роута. Проверено на `/api/daily-plan/skip-lesson` — 0 вхождений в `app/**` при заведомо живом эндпоинте. Претензия снята целиком, а не понижена |
| R8 | N+1 в листинге «Мои колоды» (`app/study/routes.py:95-150`) | Прочитано: колоды, `QuizDeckWord`, `UserWord` и `UserCardDirection` берутся четырьмя батч-запросами по `in_(...)`, затем раскладываются в словари. Цикла с ленивой подгрузкой нет |

---

## Зона Админка

> **Task 5** — закрыт. Инвентаризация **197 admin-правил** в 20 неймспейсах (19 sub-blueprint'ов +
> `reminders`, смонтированный под `/admin/reminders`), из них **115 мутирующих**; AST-разбор
> **193** route-функций в `app/admin/**` с полными цепочками декораторов. Пять линз.
> Записано **8 находок** `ADM-001…ADM-008`. Линза (г) сформулирована как список **конкретных
> недостающих метрик**, а не как «улучшить дашборд». Опровергнуто при проверке — **5 претензий**
> (`RA1…RA5`), 2 не доведены до CONFIRMED и вынесены в `PL-ADM-01…02`.

**Сводка зоны:** P0 — 0 · P1 — 1 · P2 — 4 · P3 — 3.

### Инвентаризация admin-роутов (checkbox 1)

Снято из живого `create_app()` (SQLite, `TESTING`) — те же 531 правило, что в Task 4; отфильтровано
по префиксу `/admin`.

| Неймспейс | Правил | Мутирующих | В списке гейта аудит-лога |
|---|---|---|---|
| `admin` (main_routes + book_courses + curriculum + modules + quiz_decks) | 81 | 49 | ✅ |
| `grammar_lab_admin` | 12 | 8 | ✅ |
| `user_admin` | 11 | 6 | ✅ |
| `book_admin` / `word_admin` / `audio_admin` | 10 / 10 / 10 | 8 / 7 / 6 | ✅ |
| `topic_admin` | 8 | 6 | ✅ |
| `system_admin` | 7 | 3 | ✅ |
| **`telegram_channel_admin`** | 7 | **6** | ❌ |
| `admin_curriculum` / `seo_admin` | 6 / 6 | 1 / 3 | ✅ |
| `collection_admin` | 5 | 3 | ✅ |
| **`feedback_admin`** | 5 | 3 | ❌ |
| **`word_contrast_admin`** | 5 | 4 | ❌ |
| **`reminders`** (под `/admin/reminders`) | 4 | **1** | ❌ |
| `dashboard_admin` | 3 | 0 | ❌ |
| `settings_admin` | 2 | 1 | ✅ |
| `activity_admin` / `audit_admin` | 2 / 2 | 0 / 0 | ✅ |
| `acquisition_admin` | 1 | 0 | ❌ |
| **Итого** | **197** | **115** | 15 из 20 |

**Покрытие аудит-логом по факту** (AST: `@admin_audit_required` в цепочке декораторов ИЛИ
`log_admin_action(` в теле): из 114 мутирующих функций, разобранных в `app/admin/**`, **не пишут
аудит 8**. Две из них задокументированы в `AUDIT_LOG_WHITELIST` с обоснованием
(`book_admin.extract_book_metadata` — временный файл без записи в БД;
`grammar_lab_admin.import_exercises_json` — фан-аут, аудит пишет хелпер на каждый файл).
Остальные **6** — весь мутирующий фронт `telegram_channel_admin`. Плюс `reminders.send_reminders`,
живущий вне `app/admin/` и потому не попавший в AST-скан. → `ADM-002`.

**Дубли правил.** 14 URL обслуживаются двумя эндпоинтами. 12 из 14 — легальная пара
`GET`-форма / `POST`-обработчик на одном URL. Оставшиеся 2 — настоящие коллизии:
`/admin/api/words/search` (→ `ADM-001`) и шесть `/admin/curriculum/*` (→ `ADM-006`).
Победитель определён живым `url_map.bind('localhost').match(path)`, а не рассуждением
о порядке регистрации.

**Шаблоны-сироты.** Из 102 шаблонов под `app/templates/admin/` не рендерится ни одним роутом
**3** — ровно те, что назвал `SEC-008`. Ответ на хенд-офф Task 4 — в `RA5`: они **мёртвые**, а не
потерянные.

### Индекс

| ID | Sev | Файл:строка | Симптом | Вериф. |
|---|---|---|---|---|
| ADM-001 | P1 | `app/admin/book_courses.py:1465` | Автокомплит редактора колод не видит 49% словаря: URL перехвачен book-course-хендлером | CONFIRMED |
| ADM-002 | P2 | `tests/admin/test_audit_log_coverage.py:34` | Гейт покрытия аудит-логом слеп к 5 из 20 неймспейсов; 7 мутирующих роутов не пишут `AdminAuditLog` | CONFIRMED |
| ADM-003 | P2 | `app/admin/routes/dashboard_routes.py:700` | Content-quality dashboard не показывает ни одного класса дефектов зоны «Контент» | CONFIRMED |
| ADM-004 | P2 | `app/admin/curriculum.py:449`, `:532`, `:610`, `:674` | Четыре структурных редактора уроков не имеют ни одной точки входа | CONFIRMED |
| ADM-005 | P2 | `app/admin/routes/curriculum_routes.py:94` | `/admin/curriculum/lessons` рендерит все 1548 уроков без пагинации, `lesson.module.level` — ленивый | CONFIRMED |
| ADM-006 | P3 | `app/admin/main_routes.py:65`, `:91`, `:131` | 6 curriculum-роутов в `main_routes.py` перекрыты копиями из `admin_curriculum` | CONFIRMED |
| ADM-007 | P3 | `app/admin/routes/audit_routes.py:124` | 5 из 7 экспортов не пишут `log_admin_action` — включая экспорт самого аудит-лога | CONFIRMED |
| ADM-008 | P3 | `app/admin/main_routes.py:108` | Валидаторы `get_*_arg` применены в 2 из 19 route-модулей; 4 живых `ilike` без `escape_like` | CONFIRMED |

### P1 — детали

**ADM-001 · `app/admin/book_courses.py:1465` (побеждает) vs `app/admin/quiz_decks.py:502` (мёртв) · blueprint `admin` · коллизия правил**

Два эндпоинта одного blueprint'а зарегистрированы на **одном URL** `/admin/api/words/search`:

| Эндпоинт | Файл | Что делает |
|---|---|---|
| `admin.search_words_api` | `book_courses.py:1465` | **INNER JOIN `word_book_link`** → только слова, привязанные к книге; сортировка по частоте в книге; жёсткий `.limit(15)`; параметр `limit` **игнорируется**; фильтра на непустой `russian_word` нет |
| `admin.api_words_search` | `quiz_decks.py:502` | фильтрует `russian_word IS NOT NULL AND != ''`, умная сортировка (точное совпадение → префикс → алфавит), уважает `?limit` (cap 50) |

`register_book_course_routes(admin)` вызывается первым в `register_admin_routes`
(`app/admin/__init__.py:14-16`), `import app.admin.quiz_decks` — позже, поэтому правило из
`book_courses.py` попадает в `url_map` раньше и **выигрывает**. Проверено живым матчингом:
`url_map.bind('localhost').match('/admin/api/words/search')` → `admin.search_words_api`.
Второй view недостижим по URL.

Единственный потребитель — автокомплит редактора колод:
`app/static/js/quiz-deck-editor.js:64` → `fetch('/admin/api/words/search?q=…&limit=10')`,
подключён из `app/templates/admin/quiz_decks/edit.html:207`.

Сценарий отказа (числа с `learn_db_prod`): в `collection_words` **25 089** слов, строку в
`word_book_link` имеют **12 767**; значит **12 322 слова (49.1%)** не могут быть возвращены
автокомплиту никогда — inner join их отсекает. Админ, собирающий колоду из курсовой лексики,
вводит слово, видит пустой выпадающий список и вынужден заполнять english+russian вручную
(обход есть — поэтому P1, а не P0). Побочно: `limit=10` из JS игнорируется (всегда 15 строк),
а отсутствие фильтра на пустой перевод даёт пункты вида `word — None` у **25** слов —
выбор такого пункта подставляет пустой русский.

Верификация: прочитаны оба view целиком; порядок регистрации подтверждён живым `match()`, а не
выведен из чтения; счётчики сняты запросами к `learn_db_prod`; `quiz-deck-editor.js:62-100`
прочитан — ответ парсится как плоский список `{id, english, russian}` (эта часть контракта у
обоих хендлеров совпадает, ломается именно выборка).

### P2 — детали

**ADM-002 · `tests/admin/test_audit_log_coverage.py:34` · гейт аудит-лога слеп к пяти неймспейсам**

`ADMIN_BLUEPRINT_PREFIXES` перечисляет 15 префиксов. За пределами списка остались
`telegram_channel_admin.`, `feedback_admin.`, `word_contrast_admin.`, `acquisition_admin.`,
`dashboard_admin.` и `reminders.` — то есть `_admin_mutating_rules()` их правила отбрасывает
на строке 82 и статическая проверка на них **не запускается вовсе**. Список задан литералом и
ничем не сверяется с фактическим набором blueprint'ов под `/admin`.

Из «невидимых» неймспейсов трое пишут аудит по дисциплине автора (`feedback_admin`,
`word_contrast_admin`), у двоих мутаций нет (`dashboard_admin`, `acquisition_admin`), а
**`telegram_channel_admin` не пишет ничего** — все 6 мутирующих роутов
(`app/admin/routes/telegram_channel_routes.py:131,147,167,176,208,225`) висят на голом
`@admin_required`:

| Роут | Что делает | Обратимо? |
|---|---|---|
| `POST /telegram-channel/skip/<id>` | `post.status = skipped` + commit | да |
| `POST /telegram-channel/refill` | `queue_upcoming(days_ahead)` — создаёт посты | да |
| `POST /telegram-channel/test` | **шлёт сообщение в публичный канал** | **нет** |
| `POST /telegram-channel/publish-now` | **`publish_due()` — публикует всю готовую очередь** | **нет** |
| `POST /telegram-channel/resend/<id>` | возвращает провалившийся пост в очередь | да |
| `POST /telegram-channel/send-now/<id>` | сдвигает расписание в прошлое и **публикует** | **нет** |

Плюс `reminders.send_reminders` (`app/reminders/routes.py:647`, `POST /admin/reminders/send`,
`@admin_required`) — **массовая рассылка email** выбранным пользователям, тоже без
`AdminAuditLog`. Смягчение: факт отправки остаётся в `ReminderLog` per-user, но привязки
«какой админ запустил какую кампанию» там нет.

Сценарий отказа: в канал уходит ошибочный пост либо рассылка не тому сегменту; админ открывает
`/admin/audit-log`, фильтрует по дате — и не находит ни одной строки, потому что записи нет.
В `learn_db_prod` на 524 строки аудита нет ни одного `channel_post.*` и ни одного `reminder.*`.
Восстановить авторство можно только из `audit.admin`-логгера (`decorators.py:53-58`), который
пишет в файл/stdout, не в БД, и ротируется.

Верификация: прочитан весь `test_audit_log_coverage.py`; AST-скан 114 мутирующих функций
`app/admin/**`; прочитан `telegram_channel_routes.py` целиком и `reminders/routes.py:647-700`;
`select action, count(*) from admin_audit_log group by 1` на `learn_db_prod`.
⚠️ Severity — судейское решение: пользовательского бага здесь нет (это контроль
подотчётности), поэтому не P1; но и не косметика — нарушен инвариант, который проект специально
закрыл тестом. Записано P2; второй проход Task 6 вправе передвинуть.

**ADM-003 · `app/admin/routes/dashboard_routes.py:700` (`get_content_quality_detail`) и `:629` (`get_content_quality`) · дашборд слеп к дефектам зоны «Контент»**

Что дашборд показывает сегодня: `by_type` (audio / IPA / examples / completion в процентах),
`missing_audio` (уроки типов `dictation`/`listening_immersion`/`shadow_reading`/`audio_fill_blank`
без `content.audio_url`), `no_vocabulary`, `low_pass_lessons` (pass-rate < 50% при ≥5 попытках),
`zero_completions_count`, `zero_exercises_count`.

Зона «Контент» (Task 3) записала **33 находки**. Дашборд не показывает **ни одну** из них.
Ниже — не «сделать лучше», а конкретные недостающие представления, каждое привязано к находке
и к уже существующему источнику данных:

| Недостающая метрика | Какой источник | Какую находку сделала бы видимой | Сколько бы показала сегодня |
|---|---|---|---|
| **Битые ссылки на аудио слов**: доля `collection_words.listening`, чей файл отсутствует под `app/static/` | `collection_words` × листинг файлов | `CNT-003` | **1570 из 1580** слов курсовой лексики (99.4%) — кнопка озвучки мертва |
| **Типы упражнений, которых шаблон не умеет рисовать**: срез `content.exercises[].type` по каждому шаблону-рендереру | `lessons.content` × `_CANONICAL_LESSON_ROUTE_TYPES` | `CNT-001`, `CNT-002`, `CNT-016`, `CNT-031` | 105 `matching` в финальных тестах + 14 `matching` в `reading` |
| **Утечки генератора**: счётчик уроков, содержащих фразы из словаря `validate_corpus.py` | `lessons.content` × словарь валидатора | `CNT-006`, `CNT-007`, `CNT-009`, `CNT-026` | 196 + 174 + 148 строк в 33/18/42 модулях |
| **`duration_seconds = 0/None` на аудио-уроках** | `lessons.content` | `CNT-015` | 86 `audio_fill_blank` + 24 урока с `0` |
| **Полнота данных гейтинга**: модули с пустым `prerequisites` среди входных модулей уровня + `prerequisites`, которые парсер не понимает | `modules.prerequisites` | `CNT-005`, `CNT-014` | 4 входных модуля без защиты, 2 нераспознанных формата |
| **Заполненность метаданных слова** (IPA / synonyms / antonyms / frequency_band / etymology) — сейчас `with_ipa` считается **только** для `vocabulary`-уроков и только как «в коллекции есть хоть одно слово с IPA» | `collection_words` | `CNT-018`, `CNT-019` | 19.7% по всей базе; 1908 строк-литералов `["null"]` |

Отдельный дефект той же функции: `with_ipa` / `with_examples` инкрементируются исключительно
внутри `if lt == 'vocabulary'` (строки 772-778), а `ipa_pct` / `examples_pct` вычисляются в
`type_rows` для **каждого** типа (строки 824-826). В базе **17** различных `lessons.type`;
`vocabulary` — один из них. Значит **16 строк из 17** показывают `0 (0%)` в колонках IPA и
«Примеры» **по построению**, а не потому, что данных нет. Админ читает таблицу как список
проблем и получает 16 ложных.

Проверено и **не** заявлено: `content.audio_url` на уровне урока в порядке — все **344** урока
со значением ссылаются на существующий файл, а у всех 4 «аудио-обязательных» типов (86 уроков
каждый) `audio_url` заполнен. То есть `missing_audio_count = 0` — правда; неправда — что аудио
в курсе исправно, потому что мёртвыми оказались ссылки на аудио **слов**, которых дашборд
не касается вовсе.

Верификация: прочитаны `get_content_quality`, `get_content_quality_detail`,
`content_quality_export`, `app/templates/admin/content_quality.html`; счётчики сняты запросами
к `learn_db_prod` + обходом 5140 mp3 под `app/static/`; 1570 битых ссылок пересчитаны
независимо от Task 3 и сошлись.

**ADM-004 · `app/admin/curriculum.py:449`, `:532`, `:610`, `:674` · четыре редактора без точки входа**

`edit_grammar_lesson`, `edit_quiz_lesson`, `edit_matching_lesson`, `edit_text_lesson` —
четыре полноценных `GET|POST`-страницы со своими шаблонами
(`admin/curriculum/edit_{grammar,quiz,matching,text}.html`), формами по структуре упражнения и
записью в `lessons.content`. Строк `url_for('admin.edit_quiz_lesson', …)` (и трёх остальных) —
**0** во всём `app/**`; литеральных путей `/curriculum/lessons/<id>/edit_quiz` в шаблонах и JS —
тоже 0. Кнопка «Edit» в списке уроков (`admin/curriculum/lesson_list.html:123`) ведёт на
`curriculum_admin.edit_lesson`.

Сценарий отказа: админу нужно поправить 105 сломанных `matching`-вопросов из `CNT-001`. Форма
для этого написана (`edit_matching`), но попасть в неё можно только вручную набрав URL —
чего никто не сделает, не читая исходников. Фактический путь — `curriculum_admin.edit_lesson`
(`app/curriculum/routes/admin.py:316`), где `content` правится **как сырой JSON в textarea**
с единственной проверкой `json.loads` + «это dict или list». То есть цель достижима, но через
ручную правку JSON вместо готовой формы — определение P2.

Верификация: прочитаны все четыре view и `curriculum_admin.edit_lesson`; grep по `app/**`
(`.py`/`.html`/`.js`) на имена эндпоинтов и на литеральные хвосты путей — 0 вхождений вне самих
определений и шаблонов.

**ADM-005 · `app/admin/routes/curriculum_routes.py:94` (`admin_curriculum.lesson_list`) · страница на 1548 строк без пагинации**

`query.order_by(...).all()` — без `paginate()`, без `limit`. В `learn_db_prod` **1548** уроков,
и при пустых фильтрах все они уходят в шаблон. `admin/curriculum/lesson_list.html:86,89`
обращается к `lesson.module.level.code` и `lesson.module.number`; `Lessons.module`
(`app/curriculum/models.py:251`) и `Module.level` (`:73`) — обычные `relationship` с
`lazy='select'`. Identity map схлопывает повторы, поэтому дополнительных запросов не 1548×2,
а **86 + 5 = 91** — по числу различных модулей и уровней. Итого ~92 запроса и один HTML на
1548 строк таблицы на каждое открытие страницы.

Сценарий отказа: админ открывает «Уроки» без фильтра — браузер получает многомегабайтную
таблицу, а сервер выполняет 92 запроса вместо 1. Фильтры по уровню/модулю работают и
сокращают выборку, поэтому цель достижима — P2, не выше. Соседний
`admin_curriculum.module_list` (`:68`) имеет тот же класс дефекта в явном виде:
`for module in modules: Lessons.query.filter_by(...).count()` — 86 COUNT-запросов в цикле
(та же строка продублирована в `main_routes.py:79`, см. `ADM-006`).

⚠️ Замера рантайма **не делалось** — вывод про 92 запроса получен чтением кода и подсчётом
кардинальностей (`select count(*)` по `lessons` / `modules` / `cefr_levels` на
`learn_db_prod`), а не профилировщиком. Записано как CONFIRMED в части «пагинации нет и
`relationship` ленивый» (это факт кода); точное число запросов — производная оценка.

### P3 — детали

**ADM-006 · `app/admin/main_routes.py:65`, `:91`, `:131` (+ `curriculum`, `level_list`, `import_curriculum`)** —
шесть роутов из `main_routes.py` (blueprint `admin`) зарегистрированы на тех же URL, что и их
копии из `curriculum_routes.py` (blueprint `admin_curriculum`): `/admin/curriculum`,
`/admin/curriculum/levels`, `/admin/curriculum/modules`, `/admin/curriculum/lessons`,
`/admin/curriculum/progress`, `/admin/curriculum/import`. `curriculum_bp` регистрируется в
`register_admin_routes` раньше, чем сам blueprint `admin` (он идёт последним,
`app/admin/__init__.py:100`), поэтому во **всех шести** случаях выигрывает `admin_curriculum.*` —
проверено живым `match()`. Тела копий совпадают построчно вплоть до комментариев.

Дефект — не в поведении (копии идентичны), а в ловушке: правка, внесённая в `main_routes.py`,
не вступит в силу и не даст никакого сигнала. `tests/admin/test_legacy_admin_routes.py:23-49`
буквально озаглавлен «Smoke tests for legacy admin routes **in main_routes.py**» и ходит по этим
шести URL — то есть тест зелёный, а покрывает он другой файл. `url_for('admin.lesson_list')`
по-прежнему строится (эндпоинт существует) и ведёт на чужой хендлер.

**ADM-007 · `app/admin/routes/audit_routes.py:124` (+ 4 места)** — конвенция (CLAUDE.md, раздел
Admin): «CSV export — sanitize через `_sanitize_csv_cell()`, `MAX_EXPORT_ROWS`, streaming,
**audit log**». Санитизация и лимит соблюдены везде (см. `RA2`), аудит — нет:

| Роут | `log_admin_action` |
|---|---|
| `user_admin.export_users_csv` (`user_routes.py:380`) | ✅ `user.export_csv` |
| `user_admin.stats?export=csv` (`user_routes.py:451`) | ✅ `stats.export_csv` |
| **`audit_admin.audit_export_csv`** (`audit_routes.py:124`) | ❌ |
| **`dashboard_admin.content_quality_export`** (`dashboard_routes.py:953`) | ❌ |
| **`word_admin.export_words`** (`word_routes.py:107`) | ❌ |
| **`admin.export_lesson`** (`curriculum.py:766`) | ❌ |
| **`admin.quiz_deck_export`** (`quiz_decks.py:372`) | ❌ |

Отдельно стоит первый из невыгружающих: **экспорт самого аудит-лога не оставляет следа в
аудит-логе**. P3 — все пять под `@admin_required`, утечки за периметр админов нет, теряется
только атрибуция выгрузки.

**ADM-008 · `app/admin/main_routes.py:108`, `app/admin/routes/curriculum_routes.py:111`,
`app/admin/quiz_decks.py:521`, `app/admin/book_courses.py:1485`** — два разошедшихся долга по
валидации ввода:

*Валидаторы.* `app/admin/utils/request_validators.py` (`get_int_arg` / `get_enum_arg` /
`get_choice_arg`, `abort(400)` вместо тихой деградации) вызывается **5 раз** в **2** из 19
route-модулей (`word_routes.py`, `user_routes.py`). Всего чтений `request.args` в `app/admin/**`
— **92**. Остальные идут либо через `request.args.get(..., type=int)` (werkzeug молча возвращает
default на мусоре — ровно то поведение, против которого написан `get_int_arg`), либо через
`int(...)` в `try/except`. Ни одного пути к 500 из-за этого не найдено (см. `RA1`), поэтому это
расхождение конвенции, а не баг.

*`escape_like`.* Хелпер применён в 8 местах, но 4 живых `ilike` строят паттерн из сырого ввода:
`Lessons.title.ilike(f'%{search}%')` в `main_routes.py:108` и `curriculum_routes.py:111`,
`CollectionWords.{english,russian}_word.ilike(f'%{query}%')` в `quiz_decks.py:521-522` и
`book_courses.py:1485`. SQL-инъекции нет (параметры связаны), ломается только точность поиска:
`_` совпадает с любым символом, `%` — с любой подстрокой. Админ, ищущий урок `Present_Simple`,
получит лишние совпадения.

### Опровергнуто при проверке — не переоткрывать без новых фактов

| # | Претензия | Почему опровергнуто |
|---|---|---|
| RA1 | `admin.api_words_search` (`quiz_decks.py:507`) делает `min(int(request.args.get('limit', 10)), 50)` без охраны → `?limit=abc` даёт 500, `?limit=-5` — отрицательный `LIMIT` | View **недостижим**: то же правило перехватывает `admin.search_words_api` (см. `ADM-001`), живой `match()` это подтверждает. Дефект существует только в мёртвом коде и отдельной находкой не заводится. Проверены и остальные сырые `int(request.args…)`: `collection_routes.py:72,76` обёрнуты в `try/except`, `book_courses.py:1472` — `type=int` |
| RA2 | CSV-экспорты админки не санитизируются и не ограничены по строкам | Прочитаны все 4 CSV-писателя: `export_helpers._stream_csv_rows` + `_sanitize_csv_cell` + `MAX_EXPORT_ROWS` (`words`, `audio`, `audit-log`), `user_routes.py:402,467` (`_sanitize_csv_cell` на каждую ячейку, срез `[:MAX_EXPORT_ROWS]`), `dashboard_routes.py:964` (`_sanitize_csv_cell` + срез). Незакрытых мест нет; недостаёт только аудит-записи → `ADM-007` |
| RA3 | Пагинация админских листингов теряет активные фильтры при переходе на следующую страницу | Прочитаны 5 шаблонов с пагинацией: `admin/audit/index.html:130,140`, `feedback/index.html:197,207`, `users.html:418-432`, `word_contrasts/index.html:153,157`, `collections/list.html:168-188`. Все прокидывают фильтры в `url_for` (`collections` — через `**pagination_args`). Ни одного случая потери |
| RA4 | Админские загрузки файлов идут мимо `app/utils/file_security.py` | Прочитаны все 6 путей: `main_routes.py:212`, `word_routes.py:149,448`, `book_routes.py:226`, `curriculum_routes.py:215` — все зовут `validate_text_file_upload`; `book_processing_service._save_upload` (`:64-94`) — `secure_filename` + whitelist расширений + проверка размера + сверка `realpath` на выход из каталога; `word_contrast_import` (`word_contrast_routes.py:221`) — cap размера, `utf-8`-декод, построчный парсер, на диск ничего не пишет; `_import_exercises_json_file` — `json.loads` + `validate_exercise_content` на каждое упражнение, на диск не пишет |
| RA5 | Хенд-офф `SEC-008`: `admin/book_courses/{create_module,edit_module,index}.html` — потерянные страницы, а не мёртвые | **Мёртвые.** Роутов CRUD модулей курса не существует вовсе: в `url_map` под `/admin/book-courses/**/modules/**` есть только `view_course_module` (GET) и операции над **уроками**; модули создаются исключительно `admin.generate_course_modules` (POST, генератор из книги). Ручного создания/редактирования модуля в продукте нет — значит `create_module.html`/`edit_module.html` пережили удаление своих роутов. `index.html` вытеснен `list.html`, который и рендерит `admin.book_courses` |

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

### Зона Контент (Task 3)

Все 33 записанные находки перепроверены по первоисточнику (JSON / БД / код), поэтому PLAUSIBLE в
основном списке нет. Ниже — претензии финдеров, которые **не удалось довести до CONFIRMED** и
которые поэтому в реестр не вошли и в ремедиацию не берутся.

| # | Претензия | Почему не CONFIRMED |
|---|---|---|
| PL-CNT-01 | 180 `listening_quiz`-упражнений, где аудио произносит только сам ответ («What did the customer order?» → аудио «A spicy pasta») | Отделить дефект от легального узнавания слова можно лишь на слух; фильтр «вопрос сформулирован как comprehension» — эвристика финдера, я её не воспроизводил |
| PL-CNT-02 | 46 полей `translation`, содержащих английский вместо русского | Не перепроверено пофайлово; часть случаев (`A2_2` matching «How many?» → «apples, books, shops») по инструкции упражнения выглядит намеренной |
| PL-CNT-03 | 12 модулей, где русский перевод immersion-текста покрывает <60% предложений | Порог 60% выбран финдером произвольно; не проверено, рендерится ли перевод целиком или по предложениям |
| PL-CNT-04 | 130 межмодульных дублей заголовочных слов, из них 18 с конфликтующими глоссами (`holiday` = «отпуск» vs «праздник») | Правдоподобно и подкреплено примерами, но влияние на SRS (какой глосс выигрывает в карточке) я не проследил по коду |
| PL-CNT-05 | 49 уроков «Слушаем диалог», содержащих монолог | Признак «нет реплик» не формализован; выборочная проверка подтверждает, полный счёт — нет |
| PL-CNT-06 | 88% значений `etymology` — шаблонные («От first и day») | Оценка качества, а не дефект; порога «шаблонности» не задано |
| PL-CNT-07 | 87 immersion-ассетов, у которых номер модуля в имени файла на 1 расходится с модулем | Файлы существуют и играют; дефекта поведения нет. Смежно с CNT-008, где такой же сдвиг **привёл** к коллизии — но там доказана именно коллизия |
| PL-CNT-08 | 60 значений `dictation.gaps[].source_word_index` указывают на другое слово | Поле не читает ни один потребитель в `app/` (только `scripts/create_*.py` пишет) — дефект без сценария отказа |

### Зона Разделы (Task 4)

Из 8 записанных находок все 8 доведены до CONFIRMED чтением кода (плюс живой `BuildError` и
запросы к `learn_db_prod`). Ниже — то, что **осталось недоказанным** и потому в реестр не вошло.

| # | Файл:строка | Претензия | Почему не CONFIRMED |
|---|---|---|---|
| PL-SEC-01 | `app/study/routes.py:124,133`; `app/study/services/srs_service.py:41,92`; `app/srs/service.py:1079,1162,1303` | Списки id пользователя (`all_deck_word_ids`, `user_word_ids`, `word_ids`) уходят в `.in_(...)` без `chunk_ids` — при росте словаря запрос упрётся в лимит параметров драйвера | Замерено на `learn_db_prod`: максимальная колода — **414** слов, максимум `user_words` на пользователя — **810**, при пороге `chunk_ids` в 1000. Сегодня сценария отказа не существует; это масштабирование, а не дефект. Всего мест с «сырым» `.in_(переменная)` — **188**, из них через `chunk_ids` идут 12 |
| PL-SEC-02 | `app/books/routes.py:418` (`?from=javascript:…`) | Клик-XSS в аутентифицированном контексте ридера | Открытый редирект доказан и записан как `SEC-002`; именно `javascript:`-вариант зависит от того, как браузер применяет `script-src 'unsafe-inline'` рядом с nonce (CSP3). В браузере не проверялось — заявлять исполнение скрипта не могу |
| PL-SEC-03 | `app/curriculum/service.py`, `card_service.py`, `books/services/book_service.py`, `books/api.py` (~40 мест) | `db.session.commit()` внутри сервисных хелперов вместо caller-commits — исключение у вызывающего оставит частичную запись | Проверены только XP-блоки (см. `R6`) — там инвариант соблюдён. Остальные сайты пофайлово не разбирались; без конкретного пути «исключение после чужого commit'а» претензия остаётся гипотезой о конвенции |
| PL-SEC-04 | `app/api/books.py:643,685,716,753` | Подсистема `Block`/`Task` целиком мертва на фронте (модели остались от старой «экзаменационной» схемы) и её следовало бы удалить, а не гейтить | В БД **84 блока и 1 803 задачи** — данные живые. Потребителей на фронте не нашёл, но доказать, что их нет (в т.ч. у внешнего JWT-клиента), поиском по репозиторию нельзя. Поэтому `SEC-001` сформулирован как «поставить гейт», а не «удалить» |

### Зона Админка (Task 5)

Из 8 записанных находок все 8 доведены до CONFIRMED (чтение кода + живой `url_map.match()` +
запросы к `learn_db_prod` + обход файловой системы). Ниже — то, что **осталось недоказанным**.

| # | Файл:строка | Претензия | Почему не CONFIRMED |
|---|---|---|---|
| PL-ADM-01 | `app/admin/utils/decorators.py:104` | `admin_audit_required` вызывает `db.session.commit()` после постановки аудит-строки. Если обёрнутый view сознательно оставил в сессии незакоммиченную работу (например, ветку «показать подтверждение»), декоратор закоммитит её как побочный эффект | Роута, который бы это воспроизводил, я не нашёл: все прочитанные аудируемые view коммитят сами до `return`. Доказать отсутствие такого роута перебором 115 мутирующих функций я не пытался — поэтому не REFUTED, а PLAUSIBLE |
| PL-ADM-02 | `app/admin/utils/export_helpers.py:38` | `_sanitize_csv_cell` смотрит только на **первый** символ ячейки; значение вида `" =cmd|'/c calc'!A1"` (ведущий пробел) проверку проходит, а Excel при импорте ведущие пробелы в ряде путей обрезает | Класс атаки реальный, но зависит от конкретного импортёра (Excel / Sheets / LibreOffice) и настроек разделителя. В таблице не проверялось; заявлять исполнение формулы без прогона не могу. Данных, куда админ мог бы положить такую строку, тоже не искал |

**Дисциплина:** ни один пункт этого приложения не идёт в Task 7–9. Чтобы попасть в ремедиацию,
находка должна пройти скептика в следующем проходе аудита.

---

## Покрытие и сознательные пропуски

> Заполняется по мере прохождения Task 2–5; Task 6 добавляет сюда результат критик-агента на полноту
> (какая линза не запускалась, какое утверждение не проверено, какой файл не прочитан).

| Зона | Просканировано | Сознательно не покрывалось | Причина |
|---|---|---|---|
| Контент | Все **86** файлов `module_completed/fixed/*.json` (1548 уроков, ~137 500 строковых листьев) машинными проходами: рекурсивный обход аудио-ссылок, симуляция грейдеров по всем 5 контейнерам упражнений + `test_sections`, полный перебор перестановок для 1078 `ordering`, shingle-Jaccard near-dup по прозе, skeleton-кластеризация `dialogue_completion_quiz`, посимвольная сверка `content` всех 1548 уроков против `learn_db_prod`. Прогнаны 4 валидатора. БД: `lessons`, `modules`, `grammar_topics`, `collection_words` (25 089), `word_collocations`, `cultural_notes`, `daily_lessons`, `users`. Файловая система: 5140 mp3 под `app/static/audio/`. Поимённо прочитаны JSON-фрагменты под каждую записанную находку + грейдеры `app/curriculum/grading.py`, `text.html`, `final_test.html`, `sentence_completion.html`, `vocabulary_lessons.py`, `grammar_quiz_lessons.py` | **Аудио никто не слушал** — STT недоступен, все аудио↔текст находки структурные. Не проверялась семантическая корректность ~30 000 русских переводов и правильность самой грамматики в `grammar.rule`/`sections`. Не оценивалась читабельность текстов (readability-метрика не считалась). ~4000 MC-упражнений не проверены на правдоподобие дистракторов. Перечисление фреймов `dialogue_completion_quiz` неполно (9 фреймов моих, 19 у финдера). Аудио-QA (битрейт, громкость, тишина) не измерялось. `grammar_exercises` (8947 строк) — вне корпуса, не аудировались. Пересказ-рециклинг (semantic, не лексический) невидим для 5-gram Jaccard | Основной барьер — отсутствие STT и невозможность оценить смысл без носителя/LLM-прохода. Остальное — сознательный кап: линзы были нацелены на дефекты, у которых есть машинно проверяемый признак, а не на редакторское качество |
| UI | Шаблоны: ~96 из 248 (без `emails/`) поимённо прочитаны — `lesson_base_template.html`, `base.html`, `public_base.html`, `admin/base.html`, 17 из 20 `curriculum/lessons/**`, 6 из 21 `curriculum/book_courses/lessons/**`, `partials/**`, `components/**` (кроме трёх), `auth/**` (кроме четырёх), `words/list_optimized.html`, `books/reader_simple.html`. JS: 26 из 40 не-вендорных. CSS: `design-system.css` (19 257 строк) целиком по правилам + `books/reader_simple.css`, `words/list_optimized.css`, `lessons/bc_phrase_cloze.css`, `flashcard-session.css`. Машинные проходы по всем 265 шаблонам: extends-граф, резолюция `_()`, извлечение кириллицы, `grep` по `fetch(`/`onclick=`/`innerHTML`/`role=progressbar` | `app/templates/admin/**` (94 из 102), `app/templates/study/**` (18 из 26), `curriculum/**` верхний уровень целиком, `books/list_optimized.html` + `details_optimized.html` (дефолтные!), подзоны `race/`, `modules/`, `onboarding/`, `landing/`, `legal/`, `feedback/`, `grammar_lab/{practice,stats}`; 14 JS-файлов (в т.ч. `share.js` — грузится на **каждой** странице обеих layout-веток); 69 из 98 CSS-файлов; `emails/**`; вендор `bootstrap.*` | Админка вынесена в Task 5 (эта линза покрыла только общий хром + два `extra_js`-дефекта). Остальное — кап в 8 находок на линзу плюс инструкция концентрироваться на highest-traffic learner-поверхностях. `emails/**` и вендор — вне зоны по брифу |
| Разделы | Машинные проходы по **всему** `app/**`: снимок `url_map` (531 правило, 52 неймспейса, methods/args/defaults), AST-инвентарь **522** route-функций с полными цепочками декораторов, извлечение и резолюция **1 118** вызовов `url_for`, сверка обязательных аргументов, AST-скан тел всех 240 мутирующих роутов на признаки владельца/гейта, перебор **188** сайтов `.in_(...)`, перебор всех вызовов `maybe_award_*`/`award_xp`/`check_all_achievements` в 7 файлах-хендлерах на обёртку savepoint'ом, подсчёт **240** ad-hoc JSON-ошибок и **386** чтений `.error`/`.message` на фронте. Поимённо прочитаны: все 13 роутов `app/api/books.py`, `app/api/decorators.py`, `app/api/books_catalog.py`, `app/books/access.py`, `app/books/routes.py` (роуты ридера), `app/uploads/routes.py`, `app/admin/utils/decorators.py`, `app/curriculum/routes/main.py::lesson_by_id`, `grammar_quiz_lessons.py::render_final_test_lesson`, `app/study/routes.py` (`cards_deck`, «Мои колоды»), `app/study/services/srs_service.py::get_card_counts`, `app/daily_plan/linear/errors.py::log_quiz_error`, `_flashcard_session.html`. Живой прогон `url_for` в `test_request_context` по 10 эндпоинтам. Запросы к `learn_db_prod`: `book`, `block`, `task`, `chapter`, `users`, `user_modules`, `system_modules`, `quiz_decks`, `quiz_deck_words`, `user_words` | **Линза (д) «пустые состояния и тупики» прогнана только точечно** — проверено 8 листинговых шаблонов на наличие empty-state, найдено 0 дефектов; обхода всех экранов не было. **Линза (в) «производительность» не доведена**: замеров количества запросов на странице не делалось, N+1 искался чтением одного листинга и статикой по `.in_(...)`; кеширование тяжёлых виджетов не проверялось. **Линза (г) «целостность транзакций»** покрыта только XP-блоками и `log_quiz_error`; ~40 сервисных `commit()` не разобраны (см. `PL-SEC-03`). Не читались тела роутов blueprint'ов `race`, `modules`, `notifications`, `legal`, `landing`, `seo`, `telegram`, `reminders`, `onboarding`, `courses`, `health_check`. Blueprint `admin` (81 правило) и 18 admin-суб-blueprint'ов сознательно не разбирались — это Task 5. Rate-limiting, CSRF-покрытие и заголовки безопасности как отдельные линзы не запускались (в брифе Task 4 их нет) | Инвентаризация и линзы (а)/(б) прогнаны по всей зоне и дали доказуемые находки; (в)/(г)/(д) упёрлись в то, что их дефекты требуют либо замера рантайма, либо обхода UI — то есть выходят за «читаю код и доказываю сценарий». Вместо правдоподобных догадок они вынесены сюда и в `PL-SEC-*` |
| Админка | Машинные проходы: снимок `url_map` по префиксу `/admin` (**197** правил, 20 неймспейсов, methods/args), AST-инвентарь **193** route-функций в `app/admin/**` с цепочками декораторов и телами, детекция покрытия аудит-логом по всем **114** мутирующим функциям, поиск дублирующихся правил (14) с разрешением победителя живым `url_map.bind().match()`, проверка всех **102** шаблонов `app/templates/admin/**` на сиротство встречным поиском по `app/**`, перебор **92** чтений `request.args` и всех `ilike`/`.like(`, перебор всех 7 экспортов и всех 6 путей загрузки файлов. Поимённо прочитаны: `app/admin/utils/decorators.py`, `audit.py`, `request_validators.py`, `export_helpers.py`, `__init__.py`, `routes/telegram_channel_routes.py` (целиком), `routes/dashboard_routes.py:629-980`, `routes/audit_routes.py`, `routes/user_routes.py:370-478`, `routes/collection_routes.py:60-120`, `routes/word_contrast_routes.py:50-240`, `routes/grammar_lab_routes.py:900-1033`, `services/book_processing_service.py:55-95`, `main_routes.py:60-135`, `routes/curriculum_routes.py:1-150`, `quiz_decks.py:500-560`, `book_courses.py:1455-1505`, `app/curriculum/routes/admin.py::edit_lesson`, `app/reminders/routes.py:647-700`, `tests/admin/test_audit_log_coverage.py`, `tests/admin/test_legacy_admin_routes.py:1-60`, `app/static/js/quiz-deck-editor.js:50-115`, `app/templates/admin/content_quality.html`, 5 шаблонов с пагинацией. Запросы к `learn_db_prod`: `collection_words` (25 089), `word_book_link`, `collection_words_link`, `lessons` (1548), `modules` (86), `cefr_levels` (5), `admin_audit_log` (524). Файловая система: 5140 mp3 под `app/static/` | **Линза (д) «админ-UI» покрыта частично**: проверены сиротство шаблонов, сохранение фильтров в пагинации и два листинга на N+1 — но обхода админки в браузере не было, битые виджеты/JS-ошибки на страницах не искались; **admin-шаблоны с `fetch(`, оставленные Task 2 в очереди (пункт 8 списка критика), не разбирались**. **Линза (в) в части «производительность» не замерялась рантаймом** — `ADM-005` стоит на чтении кода + кардинальностях, профилировщик не запускался; остальные 100+ admin-view на N+1 не проверялись. `app/admin/services/**` (12 файлов) читались только точечно под конкретные находки, сплошного разбора не было. Не проверялись: CSRF-покрытие admin-форм, rate-limiting админских роутов, права внутри `AdminAuditLog` (кто может читать чужие действия), корректность бизнес-логики импортёров (`curriculum_import_service`, `word_management_service`) — только их входные гейты. `app/admin/book_courses.py` (1659 строк) и `app/admin/curriculum.py` (974) прочитаны фрагментами, не целиком | Инвентаризация и линзы (а)/(б)/(в в части экспортов и загрузок)/(г) прогнаны по всей зоне и дали доказуемые находки. Перф-линза упирается в отсутствие замера рантайма, UI-линза — в отсутствие браузера; вместо правдоподобных догадок ограничения выписаны здесь, а два недоказанных пункта ушли в `PL-ADM-01/02` |

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
