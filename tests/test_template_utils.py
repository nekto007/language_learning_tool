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
