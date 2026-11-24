import io
import json
import stat
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from app.admin.services import content_package
from app.admin.services.content_package import read_content_package


LESSON = {
    'external_key': 'curriculum:final_test:A1:03:clothing',
    'passing_score': 75,
    'test_sections': [{'title': 'Одежда', 'exercises': [{'type': 'fill_blank', 'correct': 'shirt'}]}],
}
MODULE = {'module': {'level': 'A1', 'id': 3, 'lessons': [{'type': 'final_test', 'content': LESSON}]}}
LEGACY_MODULE = {'level': 'A1', 'module': 3, 'lessons': []}
JSON_BYTES = json.dumps(LESSON, ensure_ascii=False).encode('utf-8')


def package(*entries: tuple[str | ZipInfo, bytes], compression: int = ZIP_DEFLATED) -> io.BytesIO:
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', compression=compression) as archive:
        for member, content in entries:
            archive.writestr(member, content)
    buffer.seek(0)
    return buffer


def test_read_module_formats_lesson_and_directories_in_order() -> None:
    archive = package(
        ('modules/a1/', b''),
        ('modules/a1/одежда.JSON', json.dumps(MODULE, ensure_ascii=False).encode('utf-8-sig')),
        ('modules/', b''),
        ('a1.json', json.dumps(LEGACY_MODULE).encode()),
        ('final.json', JSON_BYTES),
    )
    assert read_content_package(archive) == [
        {'name': 'modules/a1/одежда.JSON', 'data': MODULE},
        {'name': 'a1.json', 'data': LEGACY_MODULE},
        {'name': 'final.json', 'data': LESSON},
    ]


class ShortReads(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(min(size, 23))


def test_read_does_not_require_seekable_upload() -> None:
    assert read_content_package(ShortReads(package(('final.json', JSON_BYTES)).getvalue()))[0]['data'] == LESSON


@pytest.mark.parametrize('name', [
    '../module.json', '/module.json', 'a/../module.json', './module.json',
    'a\\module.json', 'a//b.json', 'C:/module.json', 'a\x01.json', 'a\u202e.json',
])
def test_unclear_names_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="имя файла"):
        read_content_package(package((name, JSON_BYTES)))


@pytest.mark.parametrize('names', [
    ('A.json', 'a.json'),
    ('Café.json', 'Cafe\u0301.json'),
    ('module.json', 'module.json/lesson.json'),
    ('module.json/lesson.json', 'module.json'),
])
def test_conflicting_entries_rejected(names: tuple[str, str]) -> None:
    with pytest.raises(ValueError, match=r"пути|имен"):
        read_content_package(package(*[(name, JSON_BYTES) for name in names]))


def test_duplicate_zip_entry_rejected() -> None:
    with pytest.warns(UserWarning, match='Duplicate name'):
        archive = package(('a.json', JSON_BYTES), ('a.json', JSON_BYTES))
    with pytest.raises(ValueError, match="повторяются"):
        read_content_package(archive)


@pytest.mark.parametrize('non_json', ['app.py', 'script.js', 'README.txt', 'dot.env', 'nested.zip'])
def test_mixed_archive_rejected_as_a_whole(non_json: str) -> None:
    with pytest.raises(ValueError, match="только файлы JSON"):
        read_content_package(package(('final.json', JSON_BYTES), (non_json, b'other')))


def test_finder_metadata_is_never_parsed_as_content() -> None:
    archive = package(
        ('modules/.DS_Store', b'\xff'), ('__MACOSX/modules/', b''),
        ('__MACOSX/modules/._final.json', b'\xff'), ('modules/final.json', JSON_BYTES),
    )
    assert read_content_package(archive) == [{'name': 'modules/final.json', 'data': LESSON}]


@pytest.mark.parametrize('name', ['__MACOSX/extra.json', '__MACOSX/._app.py', '.build.py', '.bundle.zip'])
def test_extra_files_cannot_disguise_as_finder_metadata(name: str) -> None:
    with pytest.raises(ValueError, match="только файлы JSON"):
        read_content_package(package(('final.json', JSON_BYTES), (name, JSON_BYTES)))


def test_metadata_counts_towards_limits_and_does_not_make_a_package() -> None:
    with pytest.raises(ValueError, match='от 1 до'):
        read_content_package(package(('.DS_Store', b'blob'), ('__MACOSX/._foo.json', b'blob')))
    entries = [('.DS_Store', b'xxx'), ('final.json', JSON_BYTES)]
    with patch.object(content_package, 'MAX_ENTRIES', 1), pytest.raises(ValueError, match='папок'):
        read_content_package(package(*entries))
    with patch.object(content_package, 'MAX_EXPANDED_BYTES', len(JSON_BYTES)), pytest.raises(ValueError, match='16 МБ'):
        read_content_package(package(*entries))
    link = ZipInfo('.DS_Store')
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="обычные файлы"):
        read_content_package(package(('final.json', JSON_BYTES), (link, b'elsewhere')))


@pytest.mark.parametrize('mode', [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFDIR])
def test_non_regular_member_rejected(mode: int) -> None:
    member = ZipInfo('final.json')
    member.external_attr = (mode | 0o755) << 16
    with pytest.raises(ValueError, match="обычные файлы"):
        read_content_package(package((member, JSON_BYTES)))


@pytest.mark.parametrize('raw,error', [
    (b'[]', 'объект'), (b'{}', 'external_key'), (b'{"external_key":null}', 'external_key'),
    (b'{"external_key":false}', 'external_key'), (b'{"external_key":" "}', 'external_key'),
    (b'{"external_key":"x","row":{"k":1,"k":2}}', 'ключи'),
    (b'{"external_key":"x","score":NaN}', 'числовые'),
    (b'{"external_key":"x","score":1e400}', 'числовые'),
    (b'{"external_key":', 'строке'), (b'\xff', 'UTF-8'), (b'', 'строке'),
])
def test_invalid_json_reports_file(raw: bytes, error: str) -> None:
    with pytest.raises(ValueError, match='bad.json.*' + error):
        read_content_package(package(('bad.json', raw)))


def test_truncated_archive_rejected() -> None:
    truncated = package(('final.json', JSON_BYTES)).getvalue()[:-10]
    with pytest.raises(ValueError, match="повреждён"):
        read_content_package(io.BytesIO(truncated))


def test_corrupted_member_rejected() -> None:
    raw = package(('final.json', JSON_BYTES), compression=ZIP_STORED).getvalue()
    broken = raw.replace(b'final_test', b'bad__tests', 1)
    with pytest.raises(ValueError, match="повреждён"):
        read_content_package(io.BytesIO(broken))


def test_archive_limits_checked_before_reading_json() -> None:
    archive = package(('file.json', b' ' * 500 + JSON_BYTES))
    with patch.object(content_package, 'MAX_ARCHIVE_BYTES', 20), pytest.raises(ValueError, match='Размер ZIP'):
        read_content_package(archive)
    archive.seek(0)
    with patch.object(content_package, 'MAX_EXPANDED_BYTES', 499), pytest.raises(ValueError, match='распакованных'):
        read_content_package(archive)


def test_file_and_directory_limits() -> None:
    with pytest.raises(ValueError, match='от 1 до'):
        read_content_package(package(('empty/', b'')))
    with patch.object(content_package, 'MAX_FILES', 1), pytest.raises(ValueError, match='файлов JSON'):
        read_content_package(package(('a.json', JSON_BYTES), ('b.json', JSON_BYTES)))
    with patch.object(content_package, 'MAX_ENTRIES', 1), pytest.raises(ValueError, match='папок'):
        read_content_package(package(('a/', b''), ('a/b.json', JSON_BYTES)))
