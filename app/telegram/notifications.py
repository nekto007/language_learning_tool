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
        lines.append(f'\U0001f525 {streak} дней подряд — красиво идёшь!')
        lines.append('')

    # Onboarding block for new users (unchanged logic)
    onboarding = plan.get('onboarding')
    if onboarding:
        lines.append('\U0001f4a1 С чего начать:')
        lines.append('')

        first = onboarding.get('first_lesson')
        if first:
            level = f" ({first['level_name']})" if first.get('level_name') else ''
            lines.append(f"\U0001f4da Курс{level}:")
            lines.append(f"   {first['module_title']} → {first['title']}")
            if site_url:
                lines.append(f'   \U0001f517 {site_url}/curriculum/levels')
            lines.append('')

        books = onboarding.get('available_books')
        if books:
            total = onboarding.get('total_books', len(books))
            lines.append(f'\U0001f4d5 Книги ({total} шт.):')
            for b in books:
                lvl = f" [{b['level']}]" if b.get('level') else ''
                lines.append(f"   • {b['title']}{lvl}")
            if total > len(books):
                lines.append(f'   ...и ещё {total - len(books)}')
            if site_url:
                lines.append(f'   \U0001f517 {site_url}/curriculum/book-courses')
            lines.append('')

        if onboarding.get('no_words'):
            lines.append('\U0001f4d6 Карточки — добавь слова для повторения')
            if site_url:
                lines.append(f'   \U0001f517 {cards_url or (site_url + "/study/cards")}')
            lines.append('')

        return '\n'.join(lines)

    # Regular plan — numbered list
    lines.append('На сегодня предлагаю так:')
    lines.append('')
    step = 1

    if plan.get('next_lesson'):
        nl = plan['next_lesson']
        module_str = f"{nl['module_number']}." if nl.get('module_number') else ''
        lesson_type = nl.get('lesson_type')
        minutes = _lesson_minutes(lesson_type)
        lines.append(f"{step}. \U0001f3af Урок {module_str}{nl.get('lesson_order', '')} — {nl['title']} ({minutes} мин)")
        if site_url:
            lines.append(f'   \U0001f517 {site_url}/curriculum/levels')
        step += 1

    if plan.get('grammar_topic'):
        gt = plan['grammar_topic']
        due = gt.get('due_exercises', 0)
        if due > 0:
            minutes = due * 2
            lines.append(f'{step}. \u270f\ufe0f {due} упражнений по грамматике (~{minutes} мин)')
        else:
            lines.append(f'{step}. \u270f\ufe0f Грамматика: {gt["title"]}')
        if site_url:
            lines.append(f'   \U0001f517 {site_url}/grammar-lab/')
        step += 1

    if plan.get('words_due', 0) > 0:
        words = plan['words_due']
        minutes = _words_minutes(words)
        lines.append(f'{step}. \U0001f4d6 {words} слов на повторение (~{minutes} мин)')
        word_url = cards_url or (site_url + '/study/cards') if site_url else ''
        if word_url:
            lines.append(f'   \U0001f517 {word_url}')
        step += 1

    if plan.get('book_to_read'):
        lines.append(f"{step}. \U0001f4d5 Почитать: {plan['book_to_read']['title']} (5–10 мин)")
        if site_url:
            lines.append(f'   \U0001f517 {site_url}/curriculum/book-courses')

    lines.append('')
    lines.append('Хочешь — просто сделай пункт 1, и день уже засчитан \U0001f44d')

    return '\n'.join(lines)


def format_evening_summary(user_name: str, summary: dict[str, Any],
                           streak: int, site_url: str,
                           tomorrow: dict[str, Any] | None = None) -> tuple[str, dict | None]:
    """Format evening summary with praise and reflection buttons.

    Returns (text, reply_markup) tuple.
    """
    lines = [f'Классный день, {user_name}! \U0001f525', '']

    # Achievements
    if summary.get('lessons_completed'):
        count = len(summary['lessons_completed'])
        for title in summary['lessons_completed']:
            lines.append(f'\u2705 {title} — пройден')
        if count >= 2:
            lines.append('   впечатляет!')

    if summary.get('grammar_exercises', 0) > 0:
        correct = summary.get('grammar_correct', 0)
        total = summary['grammar_exercises']
        line = f'\u2705 {correct}/{total} упражнений верно'
        if total > 0 and correct / total >= 0.8:
            line += ' — хорошая точность!'
        lines.append(line)

    if summary.get('words_reviewed', 0) > 0:
        words = summary['words_reviewed']
        line = f'\u2705 {words} слов повторено'
        if words >= 20:
            line += ' — солидная работа'
        lines.append(line)

    if summary.get('books_read'):
        for title in summary['books_read']:
            lines.append(f'\U0001f4d6 Читал: {title}')

    lines.append('')
    if streak > 0:
        lines.append(f'Стрик: {streak} дней')

    # Tomorrow preview
    if tomorrow:
        module_str = f"{tomorrow['module_number']}." if tomorrow.get('module_number') else ''
        lesson_type = tomorrow.get('lesson_type')
        minutes = _lesson_minutes(lesson_type)
        lines.append('')
        lines.append(f"Завтра: Урок {module_str}{tomorrow.get('lesson_order', '')} — {tomorrow['title']} (~{minutes} мин)")
        if site_url:
            lines.append(f'\U0001f517 {site_url}/curriculum/levels')

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
    """Format midday nudge — personal and specific."""
    lines = [f'Эй, {user_name} \U0001f642', '']

    if quick_action:
        label = quick_action['label']
        minutes = quick_action['minutes']
        lines.append(f'Давай совсем маленький шаг — {label} (~{minutes} мин).')
        if quick_action['type'] == 'words' and (cards_url or site_url):
            url = cards_url or (site_url + '/study/cards')
            lines.append(f'\U0001f517 {url}')
        elif quick_action['type'] == 'grammar' and site_url:
            lines.append(f'\U0001f517 {site_url}/grammar-lab/')
        elif quick_action['type'] == 'lesson' and site_url:
            lines.append(f'\U0001f517 {site_url}/curriculum/levels')
    else:
        lines.append('Давай совсем маленький шаг — 5 минут повторения.')
        url = cards_url or (site_url + '/study/cards') if site_url else ''
        if url:
            lines.append(f'\U0001f517 {url}')

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
            lines.append(f'\U0001f517 {site_url}/curriculum/levels')
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
