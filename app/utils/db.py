from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# word_book_link is now defined in app/words/models.py (after models are loaded)
# Re-export here for backward compatibility
def get_word_book_link():
    """Lazy getter for word_book_link table to avoid circular imports"""
    from app.words.models import word_book_link
    return word_book_link

# For backward compatibility with existing imports
# This will be resolved lazily when accessed
class _WordBookLinkProxy:
    """Proxy object that lazily loads word_book_link table"""
    _table = None

    def _get_table(self):
        if self._table is None:
            from app.words.models import word_book_link
            self._table = word_book_link
        return self._table

    def __getattr__(self, name):
        return getattr(self._get_table(), name)

    @property
    def c(self):
        return self._get_table().c

    # SQLAlchemy 2.0 compatibility - used in select_from(), join(), etc.
    def __clause_element__(self):
        return self._get_table()

word_book_link = _WordBookLinkProxy()


# Удаляем определение user_word_status

def status_to_string(status_int):
    """
    Преобразует цифровой статус в строковый для модели UserWord

    0 = 'new' (новое слово)
    1 = 'learning' (изучаемое)
    2 = 'review' (на повторении)
    3 = 'mastered' (изучено)
    """
    status_map = {
        0: 'new',
        1: 'learning',
        2: 'review',
        3: 'mastered'
    }
    return status_map.get(status_int, 'new')


def string_to_status(status_string):
    """
    Преобразует строковый статус в цифровой для API совместимости

    'new' = 0
    'learning' = 1
    'review' = 2
    'mastered' = 3
    """
    status_map = {
        'new': 0,
        'learning': 1,
        'review': 2,
        'mastered': 3,
        'active': 3  # Alias for mastered
    }
    return status_map.get(status_string, 0)
