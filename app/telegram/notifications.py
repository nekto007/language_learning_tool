"""Format notification messages for Telegram bot."""
from typing import Any


def format_morning_reminder(user_name: str, streak: int,
                            plan: dict[str, Any], site_url: str) -> str:
    """Format morning reminder message."""
    lines = [f'Доброе утро, {user_name}!', '']

    if streak > 0:
        lines.append(f'🔥 Стрик: {streak} дн. подряд')
        lines.append('')

    # Onboarding block for new users
    onboarding = plan.get('onboarding')
    if onboarding:
        lines.append('💡 С чего начать:')
        lines.append('')

        first = onboarding.get('first_lesson')
        if first:
            level = f" ({first['level_name']})" if first.get('level_name') else ''
            lines.append(f"📚 Курс{level}:")
            lines.append(f"   {first['module_title']} → {first['title']}")
            if site_url:
                lines.append(f'   🔗 {site_url}/curriculum/levels')
            lines.append('')

        books = onboarding.get('available_books')
        if books:
            total = onboarding.get('total_books', len(books))
            lines.append(f'📕 Книги ({total} шт.):')
            for b in books:
                lvl = f" [{b['level']}]" if b.get('level') else ''
                lines.append(f"   • {b['title']}{lvl}")
            if total > len(books):
                lines.append(f'   ...и ещё {total - len(books)}')
            if site_url:
                lines.append(f'   🔗 {site_url}/curriculum/book-courses')
            lines.append('')

        if onboarding.get('no_words'):
            lines.append('📖 Карточки — добавь слова для повторения')
            if site_url:
                lines.append(f'   🔗 {site_url}/study/cards')
            lines.append('')

        return '\n'.join(lines)

    lines.append('📋 План на сегодня:')

    if plan.get('next_lesson'):
        nl = plan['next_lesson']
        module_str = f"{nl['module_number']}." if nl.get('module_number') else ''
        lines.append(f"📚 Урок {module_str}{nl.get('lesson_order', '')} — {nl['title']}")
        if site_url:
            lines.append(f'   🔗 {site_url}/curriculum/levels')

    if plan.get('grammar_topic'):
        gt = plan['grammar_topic']
        status_label = 'теория' if gt['status'] == 'theory_completed' else 'практика'
        due_str = f" ({gt['due_exercises']} упр.)" if gt.get('due_exercises') else ''
        lines.append(f"✏️ Грамматика: {gt['title']} — {status_label}{due_str}")
        if site_url:
            lines.append(f'   🔗 {site_url}/grammar-lab/')

    if plan.get('words_due', 0) > 0:
        lines.append(f"📖 {plan['words_due']} слов на повторение")
        if site_url:
            lines.append(f'   🔗 {site_url}/study/cards')

    if plan.get('book_to_read'):
        lines.append(f"📕 Почитать: {plan['book_to_read']['title']}")
        if site_url:
            lines.append(f'   🔗 {site_url}/curriculum/book-courses')

    lines.append('')
    lines.append('Удачного дня!')

    return '\n'.join(lines)


def format_evening_summary(summary: dict[str, Any], streak: int,
                           site_url: str) -> str:
    """Format evening summary message."""
    lines = ['📝 Итоги дня', '']

    if summary.get('lessons_completed'):
        for title in summary['lessons_completed']:
            lines.append(f'✅ {title} — пройден')

    if summary.get('grammar_exercises', 0) > 0:
        correct = summary.get('grammar_correct', 0)
        total = summary['grammar_exercises']
        lines.append(f'✅ Грамматика: {total} упражнений ({correct} верно)')

    if summary.get('words_reviewed', 0) > 0:
        lines.append(f'✅ {summary["words_reviewed"]} слов повторено')

    if summary.get('books_read'):
        for title in summary['books_read']:
            lines.append(f'📖 Читал: {title}')

    lines.append('')
    if streak > 0:
        lines.append(f'Отличный день! Стрик: {streak} дн. 🔥')

    return '\n'.join(lines)


def format_nudge(site_url: str) -> str:
    """Format midday nudge message."""
    lines = [
        'Сегодня пока тихо 🙂',
        '',
        'Даже 5 минут повторения слов — это прогресс.',
    ]
    if site_url:
        lines.append(f'🔗 {site_url}/study')
    return '\n'.join(lines)


def format_streak_alert(streak: int, site_url: str) -> str:
    """Format streak protection alert."""
    lines = [
        '⚠️ Стрик под угрозой!',
        '',
        f'Твоя серия: {streak} дн. подряд.',
        'До конца дня осталось ~2 часа.',
        '',
        'Даже 5 минут практики сохранят стрик:',
    ]
    if site_url:
        lines.append(f'🔗 {site_url}/study')
    lines.append('')
    lines.append(f'Не дай {streak} дням пропасть!')
    return '\n'.join(lines)


def format_weekly_report(report: dict[str, Any], site_url: str) -> str:
    """Format weekly report message."""
    week_start = report['week_start']
    week_end = report['week_end']

    lines = [
        '📊 Неделя '
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
        lines.append(f'Стрик: {streak} дн. 🔥')

    lines.append('')

    # Comparison with previous week
    prev_lessons = report.get('prev_lessons', 0)
    curr_lessons = report.get('lessons_completed', 0)
    diff = curr_lessons - prev_lessons

    if report['active_days'] <= 1:
        # Weak week
        prev_days = report.get('prev_active_days', 0)
        if prev_days > report['active_days']:
            lines.append(f'На прошлой неделе было {prev_days} дн.')
        lines.append('Попробуй на этой неделе заниматься хотя бы через день —')
        lines.append('даже 10 минут лучше, чем ничего.')
    elif diff > 0:
        lines.append(f'📈 На {diff} уроков больше, чем на прошлой неделе!')
        lines.append('')
        lines.append('Так держать! Новая неделя — новые возможности.')
    elif diff == 0 and curr_lessons > 0:
        lines.append('Стабильный результат! Продолжай в том же духе.')
    else:
        lines.append('Новая неделя — новые возможности!')

    if site_url:
        lines.append(f'🔗 {site_url}/study')

    return '\n'.join(lines)
