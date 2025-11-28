"""
Tests for uploads routes
Тесты маршрутов загрузки файлов
"""
import pytest
import os
from unittest.mock import patch, MagicMock, mock_open
from werkzeug.exceptions import NotFound


class TestServeCover:
    """Тесты маршрута serve_cover"""

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_success_jpeg(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест успешной отдачи JPEG файла"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/jpeg', None)
        mock_send.return_value = MagicMock()

        response = client.get('/uploads/covers/test.jpg')

        assert response.status_code != 404
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['mimetype'] == 'image/jpeg'
        assert call_kwargs['as_attachment'] == False
        assert call_kwargs['max_age'] == 86400

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_success_png(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест успешной отдачи PNG файла"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/png', None)
        mock_send.return_value = MagicMock()

        response = client.get('/uploads/covers/cover.png')

        assert response.status_code != 404
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['mimetype'] == 'image/png'

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_success_gif(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест успешной отдачи GIF файла"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/gif', None)
        mock_send.return_value = MagicMock()

        response = client.get('/uploads/covers/animation.gif')

        assert response.status_code != 404
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['mimetype'] == 'image/gif'

    def test_serve_cover_unsafe_filename(self, client):
        """Тест блокировки небезопасного имени файла"""
        # Path traversal attempt
        response = client.get('/uploads/covers/../../../etc/passwd')

        assert response.status_code == 404

    def test_serve_cover_filename_with_path(self, client):
        """Тест блокировки имени файла с путем"""
        response = client.get('/uploads/covers/subdir/file.jpg')

        assert response.status_code == 404

    @patch('app.uploads.routes.os.path.exists')
    def test_serve_cover_file_not_found(self, mock_exists, client):
        """Тест когда файл не существует"""
        mock_exists.return_value = False

        response = client.get('/uploads/covers/nonexistent.jpg')

        assert response.status_code == 404

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    def test_serve_cover_path_is_directory(self, mock_exists, mock_isfile, client):
        """Тест когда путь указывает на директорию"""
        mock_exists.return_value = True
        mock_isfile.return_value = False  # It's a directory, not a file

        response = client.get('/uploads/covers/somedir')

        assert response.status_code == 404

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_disallowed_mimetype(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест обработки неразрешенного MIME-типа"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('application/pdf', None)  # Not allowed
        mock_send.return_value = MagicMock()

        response = client.get('/uploads/covers/document.pdf')

        # Should serve with fallback MIME type
        assert response.status_code != 404
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['mimetype'] == 'image/jpeg'  # Fallback

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_unknown_mimetype(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест обработки неизвестного MIME-типа"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = (None, None)  # Unknown type
        mock_send.return_value = MagicMock()

        response = client.get('/uploads/covers/file.xyz')

        # Should serve with fallback MIME type
        assert response.status_code != 404
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['mimetype'] == 'image/jpeg'  # Fallback

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    def test_serve_cover_send_file_exception(self, mock_send, mock_exists, mock_isfile, client):
        """Тест обработки ошибки при отдаче файла"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_send.side_effect = Exception("File read error")

        response = client.get('/uploads/covers/error.jpg')

        assert response.status_code == 404

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_correct_path_construction(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест правильного построения пути к файлу"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/jpeg', None)
        mock_send.return_value = MagicMock()

        client.get('/uploads/covers/test.jpg')

        # Verify send_file was called with a path ending with uploads/covers/test.jpg
        call_args = mock_send.call_args[0]
        assert call_args[0].endswith(os.path.join('uploads', 'covers', 'test.jpg'))

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_cache_headers(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест что устанавливаются заголовки кэширования"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/jpeg', None)
        mock_send.return_value = MagicMock()

        client.get('/uploads/covers/cached.jpg')

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['conditional'] == True
        assert call_kwargs['etag'] == True
        assert call_kwargs['max_age'] == 86400  # 24 hours

    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    @patch('app.uploads.routes.send_file')
    @patch('app.uploads.routes.mimetypes.guess_type')
    def test_serve_cover_download_name(self, mock_guess, mock_send, mock_exists, mock_isfile, client):
        """Тест что устанавливается правильное имя файла для скачивания"""
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_guess.return_value = ('image/jpeg', None)
        mock_send.return_value = MagicMock()

        client.get('/uploads/covers/mycover.jpg')

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs['download_name'] == 'mycover.jpg'

    def test_serve_cover_empty_filename(self, client):
        """Тест с пустым именем файла"""
        response = client.get('/uploads/covers/')

        assert response.status_code == 404

    @patch('app.uploads.routes.logger')
    @patch('app.uploads.routes.os.path.exists')
    def test_serve_cover_logs_missing_file(self, mock_exists, mock_logger, client):
        """Тест логирования отсутствующего файла"""
        mock_exists.return_value = False

        client.get('/uploads/covers/missing.jpg')

        assert any('File not found' in str(call) for call in mock_logger.warning.call_args_list)

    @patch('app.uploads.routes.logger')
    @patch('app.uploads.routes.os.path.isfile')
    @patch('app.uploads.routes.os.path.exists')
    def test_serve_cover_logs_directory_attempt(self, mock_exists, mock_isfile, mock_logger, client):
        """Тест логирования попытки доступа к директории"""
        mock_exists.return_value = True
        mock_isfile.return_value = False

        client.get('/uploads/covers/directory')

        assert any('not a file' in str(call) for call in mock_logger.warning.call_args_list)
