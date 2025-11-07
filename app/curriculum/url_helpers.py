# app/curriculum/url_helpers.py

def get_beautiful_lesson_url(lesson):
    """Получить короткий URL для урока: /learn/{lesson_id}/"""
    return f'/learn/{lesson.id}/'


