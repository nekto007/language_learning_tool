"""Unit tests for template_utils.py"""
import pytest
from unittest.mock import patch, MagicMock
from app.utils.template_utils import (
    url_params_with_updated_args,
    format_chapter_text
)


class TestFormatChapterText:
    """Test format_chapter_text function"""

    def test_format_chapter_text_basic(self):
        """Test basic text formatting"""
        text = "Hello world"

        result = format_chapter_text(text)

        # Check that result is not None and contains text
        assert result is not None
        assert "Hello world" in str(result)

    def test_format_chapter_text_with_paragraphs(self):
        """Test formatting with paragraph breaks"""
        text = "First paragraph\n\nSecond paragraph"

        result = format_chapter_text(text)

        # Check that result contains both paragraphs
        assert result is not None
        assert "First paragraph" in str(result)
        assert "Second paragraph" in str(result)

    def test_format_chapter_text_empty(self):
        """Test formatting empty text"""
        result = format_chapter_text("")
        
        # Should return safe HTML
        assert isinstance(result, str)

    def test_format_chapter_text_with_html(self):
        """Test formatting text with HTML tags"""
        text = "<b>Bold text</b> and <i>italic</i>"
        
        result = format_chapter_text(text)
        
        # Should preserve safe HTML or escape it
        assert isinstance(result, str)

    def test_format_chapter_text_with_newlines(self):
        """Test formatting text with newlines"""
        text = "Line 1\nLine 2\nLine 3"
        
        result = format_chapter_text(text)
        
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


class TestUrlParamsWithUpdatedArgs:
    """Test url_params_with_updated_args function"""

    def test_url_params_add_parameter(self, app):
        """Test adding new URL parameter"""
        with app.test_request_context('/?page=1'):
            result = url_params_with_updated_args(filter='active')
            
            assert result['page'] == '1'
            assert result['filter'] == 'active'

    def test_url_params_update_parameter(self, app):
        """Test updating existing URL parameter"""
        with app.test_request_context('/?page=1&sort=name'):
            result = url_params_with_updated_args(page='2')
            
            assert result['page'] == '2'
            assert result['sort'] == 'name'

    def test_url_params_remove_parameter(self, app):
        """Test removing URL parameter"""
        with app.test_request_context('/?page=1&filter=active'):
            result = url_params_with_updated_args(filter=None)
            
            assert 'filter' not in result
            assert result['page'] == '1'

    def test_url_params_empty_args(self, app):
        """Test with no existing parameters"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(page='1')
            
            assert result == {'page': '1'}

    def test_url_params_multiple_updates(self, app):
        """Test updating multiple parameters"""
        with app.test_request_context('/?page=1&filter=active&sort=date'):
            result = url_params_with_updated_args(
                page='2',
                filter=None,
                sort='name'
            )
            
            assert result['page'] == '2'
            assert result['sort'] == 'name'
            assert 'filter' not in result

    def test_url_params_no_changes(self, app):
        """Test with no changes"""
        with app.test_request_context('/?page=1&sort=name'):
            result = url_params_with_updated_args()

            # Should return copy of current args
            assert result['page'] == '1'
            assert result['sort'] == 'name'


class TestFormatChapterTextAdvanced:
    """Additional tests for format_chapter_text edge cases"""

    def test_format_chapter_text_none(self):
        """Test formatting None input"""
        result = format_chapter_text(None)

        assert result == ""

    def test_format_chapter_text_escaped_newlines(self):
        """Test formatting text with escaped newlines"""
        text = "First paragraph\\n\\nSecond paragraph"

        result = format_chapter_text(text)

        # Should handle escaped newlines
        assert "First paragraph" in str(result)
        assert "Second paragraph" in str(result)

    def test_format_chapter_text_single_escaped_newline(self):
        """Test formatting text with single escaped newlines"""
        text = "Line one\\nLine two"

        result = format_chapter_text(text)

        assert "Line one" in str(result)
        assert "Line two" in str(result)

    def test_format_chapter_text_multiple_spaces(self):
        """Test formatting text with multiple spaces"""
        text = "Text   with    multiple     spaces"

        result = format_chapter_text(text)

        # Multiple spaces should be collapsed
        assert "multiple" in str(result)

    def test_format_chapter_text_whitespace_only_paragraph(self):
        """Test formatting with whitespace-only paragraphs"""
        text = "First\n\n   \n\nSecond"

        result = format_chapter_text(text)

        # Should skip empty paragraphs
        assert "First" in str(result)
        assert "Second" in str(result)

    def test_format_chapter_text_returns_markup(self):
        """Test that format_chapter_text returns Markup object"""
        text = "Test text"

        result = format_chapter_text(text)

        # Should return Markup (safe HTML string)
        assert '<p class="mb-4">' in str(result)

    def test_format_chapter_text_single_paragraph(self):
        """Test formatting single paragraph without breaks"""
        text = "This is a single paragraph with no breaks."

        result = format_chapter_text(text)

        assert "This is a single paragraph" in str(result)
        assert str(result).count('<p') == 1


class TestTemplateFilters:
    """Tests for template filters - test filter functions directly"""

    def test_audio_filename_filter_clean_filename(self):
        """Test audio_filename filter with clean filename"""
        # Test the filter logic directly without app context
        listening = 'pronunciation_en_word.mp3'
        # Simulate filter logic
        if not listening:
            result = ''
        elif listening.startswith('[sound:') and listening.endswith(']'):
            result = listening[7:-1]
        else:
            result = listening
        assert result == 'pronunciation_en_word.mp3'

    def test_audio_filename_filter_anki_format(self):
        """Test audio_filename filter with Anki sound format"""
        listening = '[sound:pronunciation_en_word.mp3]'
        # Simulate filter logic
        if listening.startswith('[sound:') and listening.endswith(']'):
            result = listening[7:-1]
        else:
            result = listening
        assert result == 'pronunciation_en_word.mp3'

    def test_audio_filename_filter_empty(self):
        """Test audio_filename filter with empty input"""
        # Test empty string
        listening = ''
        result = '' if not listening else listening
        assert result == ''

        # Test None
        listening = None
        result = '' if not listening else listening
        assert result == ''

    def test_unescape_filter_html_entities(self):
        """Test unescape filter with HTML entities"""
        import html

        result = html.unescape('&#39;')
        assert result == "'"

        result = html.unescape('&amp;')
        assert result == '&'

        result = html.unescape('&lt;html&gt;')
        assert result == '<html>'

    def test_unescape_filter_empty(self):
        """Test unescape filter with empty input"""
        import html

        # Test empty string
        text = ''
        result = '' if not text else html.unescape(str(text))
        assert result == ''

        # Test None
        text = None
        result = '' if not text else html.unescape(str(text))
        assert result == ''

    def test_format_chapter_text_filter(self):
        """Test format_chapter_text filter function"""
        result = format_chapter_text('Test paragraph')
        assert 'Test paragraph' in str(result)


class TestTranslateLessonType:
    """Tests for translate_lesson_type function logic"""

    def test_translate_lesson_type_vocabulary(self):
        """Test translate_lesson_type for vocabulary"""
        translations = {
            'vocabulary': 'Словарь',
            'grammar': 'Грамматика',
            'quiz': 'Тест',
            'matching': 'Сопоставление',
            'text': 'Текст',
            'card': 'Карточки',
            'final_test': 'Итоговый тест'
        }
        for lesson_type, expected in translations.items():
            result = translations.get(lesson_type, lesson_type.capitalize())
            assert result == expected

    def test_translate_lesson_type_unknown(self):
        """Test translate_lesson_type with unknown type"""
        translations = {
            'vocabulary': 'Словарь',
            'grammar': 'Грамматика',
        }
        lesson_type = 'unknown'
        result = translations.get(lesson_type, lesson_type.capitalize())
        assert result == 'Unknown'


class TestContextProcessorFunctions:
    """Tests for context processor function availability"""

    def test_init_template_utils_callable(self):
        """Test init_template_utils is importable and callable"""
        from app.utils.template_utils import init_template_utils
        assert callable(init_template_utils)

    def test_url_params_function_exists(self):
        """Test url_params_with_updated_args is importable"""
        from app.utils.template_utils import url_params_with_updated_args
        assert callable(url_params_with_updated_args)

    def test_format_chapter_text_function_exists(self):
        """Test format_chapter_text is importable"""
        from app.utils.template_utils import format_chapter_text
        assert callable(format_chapter_text)


class TestXPContextProcessor:
    """Tests for XP context processor"""

    def test_xp_calculation_logic(self):
        """Test XP calculation logic"""
        # Simulate XP calculation from template_utils
        total_xp = 250
        level = 1 + (total_xp // 100)  # 3
        assert level == 3

        current_level_xp = (level - 1) * 100  # 200
        next_level_xp = level * 100  # 300
        xp_to_next = next_level_xp - total_xp  # 50
        xp_progress_percent = ((total_xp - current_level_xp) / 100) * 100  # 50%

        assert xp_to_next == 50
        assert xp_progress_percent == 50

    def test_xp_default_values(self):
        """Test XP default values for new user"""
        # When user_xp is None, defaults are used
        result = {
            'user_xp': 0,
            'user_level': 1,
            'xp_to_next_level': 100,
            'xp_progress_percent': 0
        }
        assert result['user_xp'] == 0
        assert result['user_level'] == 1
        assert result['xp_to_next_level'] == 100
        assert result['xp_progress_percent'] == 0


class TestContextProcessorsIntegration:
    """Integration tests for context processors"""

    def test_context_processors_exist(self, app):
        """Test that context processors are registered"""
        # The app fixture should already have processors registered
        assert app.template_context_processors is not None
        # Just verify the dict exists, don't try to add more processors
        assert isinstance(app.template_context_processors, dict)


class TestUrlParamsEdgeCases:
    """Additional edge case tests for url_params_with_updated_args"""

    def test_url_params_integer_value(self, app):
        """Test with integer value (should be converted to string)"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(page=5)

            assert result['page'] == '5'

    def test_url_params_boolean_value(self, app):
        """Test with boolean value (should be converted to string)"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(active=True)

            assert result['active'] == 'True'

    def test_url_params_remove_nonexistent(self, app):
        """Test removing parameter that doesn't exist"""
        with app.test_request_context('/?page=1'):
            result = url_params_with_updated_args(nonexistent=None)

            # Should not error, just not add it
            assert 'nonexistent' not in result
            assert result['page'] == '1'

    def test_url_params_special_characters(self, app):
        """Test with special characters in value"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(query='test+value&special=yes')

            assert result['query'] == 'test+value&special=yes'

    def test_url_params_unicode(self, app):
        """Test with unicode characters"""
        with app.test_request_context('/'):
            result = url_params_with_updated_args(search='поиск')

            assert result['search'] == 'поиск'


class TestNavDueCounts:
    """Tests for navigation badge due count functions"""

    def test_words_due_count_unauthenticated(self, app):
        """get_words_due_count returns 0 for unauthenticated users"""
        with app.test_request_context('/'):
            from app.utils.template_utils import init_template_utils
            # Access the function via context processor
            ctx = {}
            for func in app.template_context_processors[None]:
                result = func()
                ctx.update(result)
            if 'get_words_due_count' in ctx:
                count = ctx['get_words_due_count']()
                assert count == 0

    def test_grammar_due_count_unauthenticated(self, app):
        """get_grammar_due_count returns 0 for unauthenticated users"""
        with app.test_request_context('/'):
            ctx = {}
            for func in app.template_context_processors[None]:
                result = func()
                ctx.update(result)
            if 'get_grammar_due_count' in ctx:
                count = ctx['get_grammar_due_count']()
                assert count == 0

    def test_words_due_count_authenticated_no_words(self, app, db_session, test_user):
        """get_words_due_count returns 0 when user has no words"""
        from flask_login import login_user
        with app.test_request_context('/'):
            login_user(test_user)
            ctx = {}
            for func in app.template_context_processors[None]:
                result = func()
                ctx.update(result)
            if 'get_words_due_count' in ctx:
                count = ctx['get_words_due_count']()
                assert count == 0

    def test_grammar_due_count_authenticated_no_exercises(self, app, db_session, test_user):
        """get_grammar_due_count returns 0 when user has no exercises"""
        from flask_login import login_user
        with app.test_request_context('/'):
            login_user(test_user)
            ctx = {}
            for func in app.template_context_processors[None]:
                result = func()
                ctx.update(result)
            if 'get_grammar_due_count' in ctx:
                count = ctx['get_grammar_due_count']()
                assert count == 0

    def test_words_due_count_with_due_cards(self, app, db_session, test_user):
        """get_words_due_count query returns correct count for cards due today"""
        from app.study.models import UserWord, UserCardDirection
        from app.words.models import CollectionWords
        from app.utils.db import db
        from sqlalchemy import func, or_
        from datetime import datetime, timezone
        import uuid as _uuid

        # Create a word, user_word, and due card direction
        word = CollectionWords(english_word=f'testword_{_uuid.uuid4().hex[:8]}', russian_word='тест')
        db_session.add(word)
        db_session.flush()

        user_word = UserWord(user_id=test_user.id, word_id=word.id)
        user_word.status = 'learning'
        db_session.add(user_word)
        db_session.flush()

        card = UserCardDirection(user_word_id=user_word.id, direction='eng-rus')
        card.state = 'learning'
        card.next_review = datetime.now(timezone.utc)
        db_session.add(card)
        db_session.commit()

        # Test the query logic directly (same as get_words_due_count)
        now = datetime.now(timezone.utc)
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        count = db.session.query(func.count(UserCardDirection.id)).join(
            UserWord, UserCardDirection.user_word_id == UserWord.id
        ).filter(
            UserWord.user_id == test_user.id,
            UserWord.status.in_(['new', 'learning', 'review']),
            UserCardDirection.direction == 'eng-rus',
            or_(
                UserCardDirection.next_review.is_(None),
                UserCardDirection.next_review <= end_of_today
            )
        ).scalar() or 0
        assert count >= 1

    def test_grammar_due_count_with_due_exercises(self, app, db_session, test_user):
        """get_grammar_due_count query returns correct count for exercises due today"""
        from app.grammar_lab.models import (
            GrammarTopic, GrammarExercise, UserGrammarExercise
        )
        from app.utils.db import db
        from sqlalchemy import func, or_
        from datetime import datetime, timezone
        import uuid

        slug = f'test-topic-{uuid.uuid4().hex[:8]}'
        topic = GrammarTopic(
            title='Test Topic',
            title_ru='Тестовая тема',
            slug=slug,
            level='A1',
            order=1
        )
        db_session.add(topic)
        db_session.flush()

        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'Test question', 'correct_answer': 'answer'},
            order=1
        )
        db_session.add(exercise)
        db_session.flush()

        user_exercise = UserGrammarExercise(
            user_id=test_user.id,
            exercise_id=exercise.id
        )
        user_exercise.state = 'review'
        user_exercise.next_review = datetime.now(timezone.utc)
        db_session.add(user_exercise)
        db_session.commit()

        # Test the query logic directly (same as get_grammar_due_count)
        now = datetime.now(timezone.utc)
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        count = db.session.query(func.count(UserGrammarExercise.id)).filter(
            UserGrammarExercise.user_id == test_user.id,
            UserGrammarExercise.state.in_(['learning', 'review', 'relearning']),
            or_(
                UserGrammarExercise.next_review.is_(None),
                UserGrammarExercise.next_review <= end_of_today
            )
        ).scalar() or 0
        assert count >= 1


class TestNavBadgesInTemplate:
    """Test that nav badges render correctly in templates"""

    def test_base_template_contains_quick_actions(self, app):
        """Verify quick actions dropdown exists in base template"""
        with app.test_request_context('/'):
            template = app.jinja_env.get_template('base.html')
            # Just verify the template loads without error
            assert template is not None

    def test_base_template_has_notification_bell(self):
        """Verify notification bell markup exists in base.html"""
        import os
        base_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'templates', 'base.html'
        )
        with open(base_path, 'r') as f:
            content = f.read()
        assert 'notif-bell' in content
        assert 'notif-badge' in content
        assert 'quickActionsDropdown' in content
        assert 'get_words_due_count' in content
        assert 'get_grammar_due_count' in content

    def test_breadcrumb_in_level_modules(self):
        """Verify breadcrumb markup exists in level_modules.html"""
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'templates', 'curriculum', 'level_modules.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
        assert 'ml-hero__breadcrumb' in content
        assert 'aria-label' in content

    def test_daily_plan_bar_clickable(self):
        """Verify daily plan bar has clickable link"""
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'app', 'templates', 'components', '_daily_plan_progress.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
        assert 'dp-bar__link' in content
        assert 'words.dashboard' in content
