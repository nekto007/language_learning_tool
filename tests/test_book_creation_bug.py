"""
Test for production bug: chapters_cnt NULL constraint violation
This test ensures that Book model is always created with chapters_cnt field set.

Bug report: sqlalchemy.exc.IntegrityError: null value in column "chapters_cnt" violates not-null constraint
"""
import pytest
from app.books.models import Book
from datetime import datetime, UTC


class TestBookCreationRequiredFields:
    """Tests to ensure Book model always has required fields set"""

    def test_book_creation_without_chapters_cnt_should_fail(self, db_session):
        """Test that creating Book without chapters_cnt raises error"""
        # This test documents the bug - Book MUST have chapters_cnt
        with pytest.raises(Exception):  # Will raise IntegrityError on commit
            book = Book(
                title="Test Book",
                author="Test Author",
                level="B1"
                # Missing chapters_cnt - this should fail!
            )
            db_session.add(book)
            db_session.commit()

    def test_book_creation_with_chapters_cnt_zero_succeeds(self, db_session):
        """Test that creating Book with chapters_cnt=0 works"""
        book = Book(
            title="Test Book",
            author="Test Author",
            level="B1",
            chapters_cnt=0,  # Must be set!
            created_at=datetime.now(UTC).replace(tzinfo=None)
        )
        db_session.add(book)
        db_session.commit()

        # Verify it was saved correctly
        saved_book = db_session.query(Book).filter_by(title="Test Book").first()
        assert saved_book is not None
        assert saved_book.chapters_cnt is not None  # The important part - not NULL
        assert saved_book.title == "Test Book"
        assert saved_book.author == "Test Author"

    def test_book_model_has_chapters_cnt_not_nullable(self):
        """Test that chapters_cnt column is defined as NOT NULL in model"""
        from sqlalchemy.inspection import inspect

        mapper = inspect(Book)
        chapters_cnt_column = mapper.columns['chapters_cnt']

        # Verify the column is NOT nullable
        assert chapters_cnt_column.nullable is False, \
            "chapters_cnt must be NOT NULL to prevent production bugs"
