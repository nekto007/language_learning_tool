"""Format notification messages for Telegram bot."""
from typing import Any

# Estimated minutes per lesson type
LESSON_TIME: dict[str, int] = {
    'vocabulary': 10, 'grammar': 12, 'quiz': 8, 'matching': 5,
    'text': 15, 'card': 5, 'anki_cards': 5, 'checkpoint': 15,
}


def _lesson_minutes(lesson_type: str | None) -> int:
    """Estimate minutes for a lesson type."""
    return LESSON_TIME.get(lesson_type or '', 10)


def _words_minutes(count: int) -> int:
    """Estimate minutes for word reviews (~8 cards/min)."""
    return max(count // 8, 1) if count else 0


def format_morning_reminder(user_name: str, streak: int,
                            plan: dict[str, Any], site_url: str,
                            cards_url: str = '') -> str:
    """Format morning reminder with numbered steps and focus item."""
    lines = [f'Доброе утро, {user_name} \U0001f642', '']

    if streak > 0:
        lines.append(f'\U0001f525 {streak} дней подряд \u2014 отличный темп!')
        lines.append('')

    # Onboarding block for new users
    onboarding = plan.get('onboarding')
    if onboarding:
        lines.append('Давай начнём с одного короткого шага (10\u201315 минут).')
        lines.append('')

        first = onboarding.get('first_lesson')
        if first:
            level_code = first.get('level_code', 'A1')
            module_num = first.get('module_number', 1)
            module_title = first.get('module_title', '')
            grammar = first.get('grammar_topic_title')
            minutes = first.get('estimated_minutes', 12)

            grammar_part = f' \u2014 грамматика: {grammar}' if grammar else ''
            lines.append(
                f'1. \U0001f4da {level_code} / Модуль {module_num}: '
                f'"{module_title}"{grammar_part} (~{minutes} мин)'
            )
            if site_url:
                lines.append(
                    f'   \U0001f517 {site_url}/learn/'
                    f'{level_code.lower()}/module-{module_num}/'
                )
            lines.append('')

        books = onboarding.get('available_books')
        if books:
            total = onboarding.get('total_books', len(books))
            lines.append('Если останутся силы (5\u201310 минут):')
            lines.append('')
            lines.append(f'2. \U0001f4d5 Чтение (пара страниц) \u2014 '
                         f'выбери любую книгу ({total} на выбор):')
            for b in books:
                book_url = f' \u2014 \U0001f517 {site_url}/books/{b["id"]}' if site_url else ''
                lines.append(f'   \u2022 {b["title"]}{book_url}')
            if total > len(books):
                lines.append(f'   ...и ещё {total - len(books)}')
            lines.append('   \U0001f4a1 Во время чтения: любое слово можно '
                         'перевести "на лету", послушать озвучку, '
                         'и добавить в изучение через SRS + QUIZ.')
            lines.append('')

        if onboarding.get('no_words'):
            lines.append('3. \U0001f0cf Карточки (2\u20133 мин)')
            if site_url:
                lines.append(f'   \u2022 Создай свою колоду: '
                             f'\U0001f517 {site_url}/study/my-decks/create')
                lines.append(f'   \u2022 Затем выбери слова и добавь в колоду: '
                             f'\U0001f517 {site_url}/words')
            lines.append('   Мини-цель: добавь 3\u20135 слов из урока/книги.')
            lines.append('')

        return '\n'.join(lines)

    # Regular plan — structured blocks with direct links
    step = 1

    # Block 1: Next lesson (always shown if available)
    if plan.get('next_lesson'):
        nl = plan['next_lesson']
        module_num = nl.get('module_number', '')
        lesson_type = nl.get('lesson_type')
        minutes = _lesson_minutes(lesson_type)
        lesson_id = nl.get('lesson_id')

        lines.append(f'План-минимум на сегодня (10\u201315 минут):')
        lines.append(
            f'{step}) \U0001f3af Модуль {module_num} \u2014 '
            f'следующий урок: {nl["title"]} (~{minutes} мин)'
        )
        if site_url and lesson_id:
            lines.append(f'\U0001f517 {site_url}/learn/{lesson_id}/')
        lines.append('')
        step += 1

        # "If you have extra time" separator
        extra_blocks = []
        if plan.get('grammar_topic'):
            extra_blocks.append('grammar')
        if True:  # words block is always shown
            extra_blocks.append('words')
        if plan.get('book_to_read') or plan.get('suggested_books'):
            extra_blocks.append('books')

        if extra_blocks:
            lines.append('Если есть ещё 5\u201310 минут:')
            lines.append('')

    # Block 2: Grammar quick review
    if plan.get('grammar_topic'):
        gt = plan['grammar_topic']
        topic_id = gt.get('topic_id')
        summary = gt.get('telegram_summary')

        lines.append(f'{step}) \U0001f9e0 Быстрый повтор грамматики (3\u20135 мин)')
        if summary:
            lines.append(summary)
        lines.append(f'Хочешь потренировать: Grammar Lab \u2014 {gt["title"]} + quiz')
        if site_url and topic_id:
            lines.append(f'\U0001f517 {site_url}/grammar-lab/practice/topic/{topic_id}')
        lines.append('')
        step += 1

    # Block 3: Words — review / all done / add new
    words_due = plan.get('words_due', 0)
    has_any_words = plan.get('has_any_words', False)
    lines.append(f'{step}) \U0001f4d6 Слова (3\u20135 мин)')
    if words_due > 0:
        lines.append(f'Есть {words_due} слов на повторение \u2014 просто повтори их.')
        word_url = cards_url or ((site_url + '/study/cards') if site_url else '')
        if word_url:
            lines.append(f'\U0001f517 {word_url}')
    elif has_any_words:
        lines.append('\u2705 Все слова на сегодня повторены! Завтра будут новые.')
    else:
        lines.append('Добавь 5\u201310 новых слов:')
        if site_url:
            lines.append(f'\U0001f517 {site_url}/words')
    lines.append('')
    step += 1

    # Block 4: Reading (if book_to_read or suggested_books)
    book = plan.get('book_to_read')
    suggested = plan.get('suggested_books')
    if book or suggested:
        lines.append(f'{step}) \U0001f4d5 Чтение (по желанию) 5\u201310 мин')
        if book:
            lines.append(book['title'])
            if site_url and book.get('id'):
                lines.append(f'\U0001f517 {site_url}/books/{book["id"]}')
        elif suggested:
            lines.append('Выбери книгу:')
            for sb in suggested:
                if site_url:
                    lines.append(f'\u2022 {sb["title"]} \u2014 \U0001f517 {site_url}/books/{sb["id"]}')
                else:
                    lines.append(f'\u2022 {sb["title"]}')
        lines.append('\U0001f4a1 Чтение = закрепляешь лексику в контексте '
                     '+ привыкаешь к структуре фраз.')
        lines.append('(слово \u2192 перевод/озвучка \u2192 добавить в SRS + QUIZ)')

    return '\n'.join(lines)


def _format_lesson_types(types: list[str]) -> str:
    """Deduplicate and capitalize lesson types for display."""
    label_map: dict[str, str] = {
        'vocabulary': 'Vocabulary',
        'grammar': 'Grammar',
        'quiz': 'Quiz',
        'matching': 'Matching',
        'text': 'Text',
        'card': 'Cards',
        'anki_cards': 'Cards',
        'checkpoint': 'Checkpoint',
    }
    seen: list[str] = []
    for t in types:
        label = label_map.get(t, t.capitalize())
        if label not in seen:
            seen.append(label)
    return ', '.join(seen)


def format_evening_summary(user_name: str, summary: dict[str, Any],
                           streak: int, site_url: str,
                           tomorrow: dict[str, Any] | None = None) -> tuple[str, dict | None]:
    """Format evening summary with metrics and reflection buttons.

    Returns (text, reply_markup) tuple.
    """
    lines = [f'Классный день, {user_name}! \U0001f525', '']
    lines.append('Сегодня сделал:')

    # Lessons count + types
    lessons_count = summary.get('lessons_count', 0)
    if lessons_count > 0:
        lesson_types = summary.get('lesson_types', [])
        types_str = f' ({_format_lesson_types(lesson_types)})' if lesson_types else ''
        lines.append(f'\u2705 Уроки: {lessons_count}{types_str}')

    # Grammar accuracy
    grammar_total = summary.get('grammar_exercises', 0)
    if grammar_total > 0:
        correct = summary.get('grammar_correct', 0)
        pct = round(correct / grammar_total * 100) if grammar_total else 0
        lines.append(f'\u270f\ufe0f Практика: {correct}/{grammar_total} верно ({pct}%)')

    # Words reviewed
    words = summary.get('words_reviewed', 0)
    if words > 0:
        lines.append(f'\U0001f4d6 Слова: {words} повторено')

    # Books read
    if summary.get('books_read'):
        for title in summary['books_read']:
            lines.append(f'\U0001f4d5 Чтение: {title}')

    # Streak
    if streak > 0:
        lines.append('')
        lines.append(f'\U0001f525 Стрик: {streak} дней')

    # Tomorrow preview
    if tomorrow:
        module_num = tomorrow.get('module_number', '')
        lesson_type = tomorrow.get('lesson_type')
        minutes = _lesson_minutes(lesson_type)
        lesson_id = tomorrow.get('lesson_id')
        lines.append('')
        lines.append(
            f'Завтра начнём с: Модуль {module_num} \u2192 '
            f'{tomorrow["title"]} (~{minutes} мин)'
        )
        if site_url and lesson_id:
            lines.append(f'\U0001f517 {site_url}/learn/{lesson_id}/')

    text = '\n'.join(lines)

    # Reflection inline keyboard
    reply_markup = {
        'inline_keyboard': [[
            {'text': '\U0001f60c Легко', 'callback_data': 'reflect:easy'},
            {'text': '\U0001f605 Нормально', 'callback_data': 'reflect:ok'},
            {'text': '\U0001f635 Сложно', 'callback_data': 'reflect:hard'},
        ]]
    }

    return text, reply_markup


def format_nudge(user_name: str, site_url: str,
                 quick_action: dict[str, Any] | None = None,
                 cards_url: str = '') -> str:
    """Format midday nudge — only sent when a quick action is available."""
    lines = [f'Эй, {user_name} \U0001f642', '']

    if not quick_action:
        return '\n'.join(lines)

    label = quick_action['label']
    minutes = quick_action['minutes']
    lines.append(f'Давай совсем маленький шаг \u2014 {label} (~{minutes} мин).')
    if quick_action['type'] == 'words' and (cards_url or site_url):
        url = cards_url or (site_url + '/study/cards')
        lines.append(f'\U0001f517 {url}')
    elif quick_action['type'] == 'grammar' and site_url:
        lines.append(f'\U0001f517 {site_url}/grammar-lab/')
    elif quick_action['type'] == 'lesson' and site_url:
        lines.append(f'\U0001f517 {site_url}/learn/')

    return '\n'.join(lines)


def format_streak_alert(user_name: str, streak: int, site_url: str,
                        quick_action: dict[str, Any] | None = None,
                        cards_url: str = '') -> str:
    """Format friendly streak protection — no pressure."""
    lines = [f'{user_name}, давай спасём стрик без напряга \U0001f642', '']
    lines.append(f'{streak} дней — жалко терять.')

    if quick_action:
        label = quick_action['label']
        minutes = quick_action['minutes']
        lines.append(f'Сделай {minutes} мин: {label}.')
        if quick_action['type'] == 'words' and (cards_url or site_url):
            url = cards_url or (site_url + '/study/cards')
            lines.append(f'\U0001f517 {url}')
        elif quick_action['type'] == 'grammar' and site_url:
            lines.append(f'\U0001f517 {site_url}/grammar-lab/')
        elif quick_action['type'] == 'lesson' and site_url:
            lines.append(f'\U0001f517 {site_url}/learn/')
    else:
        lines.append('Сделай 2–3 минуты: пару карточек или 1 упражнение.')
        url = cards_url or (site_url + '/study/cards') if site_url else ''
        if url:
            lines.append(f'\U0001f517 {url}')

    lines.append('')
    lines.append('Выбирай — и свободен.')

    return '\n'.join(lines)


def format_weekly_report(report: dict[str, Any], site_url: str) -> str:
    """Format weekly report message."""
    week_start = report['week_start']
    week_end = report['week_end']

    lines = [
        '\U0001f4ca Неделя '
        f'{week_start.day}.{week_start.month:02d}–{week_end.day}.{week_end.month:02d}',
        '',
    ]

    lines.append(f"Активных дней: {report['active_days']} из 7")

    if report.get('lessons_completed', 0) > 0:
        lines.append(f"Уроков пройдено: {report['lessons_completed']}")
    if report.get('exercises_done', 0) > 0:
        lines.append(f"Упражнений решено: {report['exercises_done']}")
    if report.get('words_in_srs', 0) > 0:
        lines.append(f"Слов на повторении: {report['words_in_srs']}")

    streak = report.get('streak', 0)
    if streak > 0:
        lines.append(f'Стрик: {streak} дн. \U0001f525')

    lines.append('')

    # Comparison with previous week
    prev_lessons = report.get('prev_lessons', 0)
    curr_lessons = report.get('lessons_completed', 0)
    diff = curr_lessons - prev_lessons

    if report['active_days'] <= 1:
        prev_days = report.get('prev_active_days', 0)
        if prev_days > report['active_days']:
            lines.append(f'На прошлой неделе было {prev_days} дн.')
        lines.append('Попробуй на этой неделе заниматься хотя бы через день —')
        lines.append('даже 10 минут лучше, чем ничего.')
    elif diff > 0:
        lines.append(f'\U0001f4c8 На {diff} уроков больше, чем на прошлой неделе!')
        lines.append('')
        lines.append('Так держать! Новая неделя — новые возможности.')
    elif diff == 0 and curr_lessons > 0:
        lines.append('Стабильный результат! Продолжай в том же духе.')
    else:
        lines.append('Новая неделя — новые возможности!')

    if site_url:
        lines.append(f'\U0001f517 {site_url}/study')

    return '\n'.join(lines)
