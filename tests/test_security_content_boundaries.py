"""Content boundaries without a database or production requests."""
import io
from html.parser import HTMLParser

import pytest
from PIL import Image, PngImagePlugin
from werkzeug.datastructures import FileStorage

from app.feedback import storage
from app.utils import file_security
from app.utils.template_utils import format_chapter_text


class _Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(str(text))

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize('source', [
    '<img src=x onerror=alert(1)>A story',
    '<svg onload=alert(1)><a href="javascript:alert(2)">A story</a></svg>',
    '<strong onclick="alert(1)">A story</strong>',
    '<script src="/account-data">alert(1)</script><iframe srcdoc="bad">A story</iframe>',
    '<math><mtext><img src=x onerror=alert(1)></mtext></math>',
])
def test_chapter_source_cannot_create_active_html(source):
    rendered = _Markup(format_chapter_text(source))
    assert rendered.elements
    assert all(tag in {'p', 'b', 'i', 'em', 'strong', 'u', 's', 'br', 'code', 'sub', 'sup'}
               for tag, _attrs in rendered.elements)
    assert all(not attrs or (tag == 'p' and attrs == {'class': 'mb-4'})
               for tag, attrs in rendered.elements)


def test_chapter_preserves_emphasis_and_paragraphs():
    rendered = str(format_chapter_text('A <strong>good</strong> <i>book</i>.\n\nNext chapter.'))
    assert '<strong>good</strong>' in rendered
    assert '<i>book</i>' in rendered
    assert rendered.count('<p class="mb-4">') == 2


def _png(width=20, height=10):
    image = Image.new('RGB', (width, height), (12, 34, 56))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_screenshot_pixel_limit_is_checked_before_decode(monkeypatch, tmp_path):
    data = _png()
    monkeypatch.setattr(storage, 'FEEDBACK_UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(storage, 'MAX_SCREENSHOT_PIXELS', 100)

    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError('oversized image was decoded')

    monkeypatch.setattr(PngImagePlugin.PngImageFile, 'load', unexpected_decode)
    result = storage.save_feedback_screenshot(FileStorage(stream=io.BytesIO(data), filename='shot.png'))
    assert result == (None, 'too_many_pixels')
    assert list(tmp_path.iterdir()) == []


def test_screenshot_is_resized_before_metadata_copy(monkeypatch, tmp_path):
    data = _png(60, 40)
    monkeypatch.setattr(storage, 'FEEDBACK_UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(storage, 'MAX_SCREENSHOT_DIMENSION', 20)
    copied_sizes = []
    original_copy = storage.strip_image_metadata

    def record_copy(image):
        copied_sizes.append(image.size)
        return original_copy(image)

    monkeypatch.setattr(storage, 'strip_image_metadata', record_copy)
    relative, reason = storage.save_feedback_screenshot(FileStorage(stream=io.BytesIO(data), filename='shot.png'))
    assert reason is None
    assert relative.startswith('feedback/')
    assert copied_sizes == [(20, 13)]
    with Image.open(next(tmp_path.iterdir())) as saved:
        assert saved.size == (20, 13)
        assert saved.getpixel((0, 0)) == (12, 34, 56)


def test_metadata_removal_does_not_materialize_python_pixels(monkeypatch):
    image = Image.new('RGB', (4, 4), (12, 34, 56))
    image.info['private-comment'] = 'private'

    def no_pixel_list(*_args, **_kwargs):
        raise AssertionError('one Python object per pixel must not be allocated')

    monkeypatch.setattr(image, 'getdata', no_pixel_list)
    cleaned = file_security.strip_image_metadata(image)
    assert cleaned is not image
    assert cleaned.getpixel((0, 0)) == (12, 34, 56)
    assert cleaned.info == {}
    assert image.info == {'private-comment': 'private'}


def test_metadata_removal_preserves_palette_alpha():
    image = Image.new('P', (1, 1))
    image.putpalette([255, 0, 0] + [0] * 765)
    image.info['transparency'] = 0
    cleaned = file_security.strip_image_metadata(image)
    assert cleaned.mode == 'RGBA'
    assert cleaned.getpixel((0, 0)) == (255, 0, 0, 0)
    assert cleaned.info == {}


def test_cover_pixel_budget_is_enforced_without_large_fixture(monkeypatch, tmp_path):
    path = tmp_path / 'cover.png'
    path.write_bytes(_png())
    monkeypatch.setattr(file_security, 'MAX_COVER_PIXELS', 100)
    assert file_security.validate_image_mime_type(str(path)) is False
