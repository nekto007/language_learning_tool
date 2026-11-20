"""Per-request temporary storage must not alias original book filenames."""
import inspect
import io
from pathlib import Path

from flask import Flask
import pytest
from werkzeug.datastructures import FileStorage

from app.admin.services.book_processing_service import save_uploaded_book_file
from app.books.parsers import extract_file_metadata


def upload(payload, filename='My Book.txt'):
    return FileStorage(stream=io.BytesIO(payload), filename=filename)


def test_same_filename_uploads_keep_independent_contents_and_cleanup(tmp_path):
    first, original, extension = save_uploaded_book_file(upload(b'first private book'), temp_dir=str(tmp_path))
    second, second_original, second_extension = save_uploaded_book_file(upload(b'second private book'), temp_dir=str(tmp_path))
    assert first != second
    assert original == second_original == 'My_Book.txt'
    assert extension == second_extension == '.txt'
    assert Path(first).read_bytes() == b'first private book'
    assert Path(second).read_bytes() == b'second private book'
    Path(first).unlink()
    assert Path(second).read_bytes() == b'second private book'


def test_original_filename_cannot_overwrite_preexisting_file_or_symlink(tmp_path):
    original = tmp_path / 'same.txt'
    target = tmp_path / 'synthetic.txt'
    target.write_bytes(b'unrelated content')
    original.symlink_to(target)
    saved, safe_name, extension = save_uploaded_book_file(upload(b'new book', 'same.txt'), temp_dir=str(tmp_path))
    assert safe_name == 'same.txt' and extension == '.txt'
    assert Path(saved).read_bytes() == b'new book'
    assert target.read_bytes() == b'unrelated content'
    assert original.is_symlink()


def test_partial_save_failure_removes_only_its_own_reserved_file(tmp_path, monkeypatch):
    retained, _, _ = save_uploaded_book_file(upload(b'keep this'), temp_dir=str(tmp_path))
    failed = upload(b'not saved')

    def fail_after_partial_write(destination):
        destination.write(b'partial')
        raise OSError('synthetic write failure')

    monkeypatch.setattr(failed, 'save', fail_after_partial_write)
    with pytest.raises(OSError, match='synthetic write failure'):
        save_uploaded_book_file(failed, temp_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == [Path(retained)]
    assert Path(retained).read_bytes() == b'keep this'


def test_metadata_fallback_uses_original_filename_and_legacy_call_stays_compatible():
    assert extract_file_metadata('/tmp/book-random.txt', '.txt', original_filename='My_Book.txt')['title'] == 'My_Book'
    assert extract_file_metadata('/tmp/Legacy Book.txt', '.txt')['title'] == 'Legacy Book'


def test_actual_metadata_handler_passes_original_title_and_removes_unique_temp(tmp_path, monkeypatch):
    # Minimal Flask request exercises the real handler without app startup/DB.
    from app.admin.routes import book_routes
    original_save = save_uploaded_book_file
    monkeypatch.setattr(book_routes, 'save_uploaded_book_file',
                        lambda file: original_save(file, temp_dir=str(tmp_path)))
    app = Flask(__name__)
    app.add_url_rule('/metadata', view_func=inspect.unwrap(book_routes.extract_book_metadata), methods=['POST'])
    with app.test_client() as client:
        response = client.post('/metadata', data={'file': (io.BytesIO(b'Hello.'), 'My Book.txt')})
    assert response.status_code == 200
    assert response.json['filename'] == 'My_Book.txt'
    assert response.json['metadata']['title'] == 'My_Book'
    assert list(tmp_path.iterdir()) == []
