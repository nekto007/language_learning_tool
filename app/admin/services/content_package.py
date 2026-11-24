"""Read curriculum JSON documents from an uploaded ZIP without extracting files."""
# ruff: noqa: RUF001 -- administrator-facing messages are in Russian.

import io
import json
import math
import stat
import unicodedata
import zlib
from pathlib import PurePosixPath
from typing import Any, BinaryIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 16 * 1024 * 1024
MAX_FILES = 100
MAX_ENTRIES = 2 * MAX_FILES


def _read_upload(stream: BinaryIO) -> io.BytesIO:
    buffer = io.BytesIO()
    while chunk := stream.read(64 * 1024):
        if buffer.tell() + len(chunk) > MAX_ARCHIVE_BYTES:
            raise ValueError("Размер ZIP превышает 8 МБ.")
        buffer.write(chunk)
    buffer.seek(0)
    return buffer


def _member_path(info: ZipInfo) -> PurePosixPath:
    name = info.orig_filename.removesuffix('/') if info.is_dir() else info.orig_filename
    if (
        not name or len(name) > 512 or '\\' in name or ':' in name
        or any(part in ('', '.', '..') for part in name.split('/'))
        or any(unicodedata.category(char) in ('Cc', 'Cf') for char in name)
    ):
        raise ValueError("В ZIP обнаружено недопустимое имя файла или папки.")

    kind = stat.S_IFMT(info.external_attr >> 16)
    expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    if kind not in (0, expected) or (info.external_attr & 0x10 and not info.is_dir()):
        raise ValueError("ZIP может содержать только обычные файлы и папки.")
    if info.flag_bits & 1 or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise ValueError("Нужен ZIP без пароля с обычным сжатием Deflate или без сжатия.")
    if info.is_dir() and info.file_size:
        raise ValueError("В ZIP обнаружена папка с содержимым файла.")
    return PurePosixPath(unicodedata.normalize('NFC', name).casefold())


def _json_members(archive: ZipFile) -> list[ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES:
        raise ValueError("В ZIP слишком много файлов и папок.")
    seen: set[PurePosixPath] = set()
    files: set[PurePosixPath] = set()
    directories: set[PurePosixPath] = set()
    members: list[ZipInfo] = []
    total = 0
    for info in entries:
        path = _member_path(info)
        if path in seen or any(parent in files for parent in path.parents):
            raise ValueError("В ZIP повторяются пути или совпадают имена файла и папки.")
        seen.add(path)
        directories.update(path.parents)
        if info.is_dir():
            archive.read(info)  # Validate the directory's local header and CRC as well.
            directories.add(path)
            continue
        if path in directories:
            raise ValueError("В ZIP имя файла совпадает с именем папки.")
        files.add(path)
        total += info.file_size
        original = PurePosixPath(info.filename)
        if original.name == '.DS_Store':
            continue
        if original.parts[0] == '__MACOSX' and original.name.startswith('._') and path.suffix == '.json':
            continue
        if '__macosx' in path.parts or path.suffix != '.json':
            raise ValueError("В пакет учебных материалов можно включать только файлы JSON.")
        members.append(info)
    if not members or len(members) > MAX_FILES:
        raise ValueError("В пакете должно быть от 1 до 100 файлов JSON.")
    if total > MAX_EXPANDED_BYTES:
        raise ValueError("Общий размер распакованных файлов превышает 16 МБ.")
    return members


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("повторяется ключ JSON")
        result[key] = value
    return result


def _finite_number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("число вне допустимого диапазона")
    return value


def _document(content: bytes, name: str) -> dict[str, Any]:
    try:
        data = json.loads(
            content.decode('utf-8-sig'), object_pairs_hook=_unique_keys,
            parse_float=_finite_number, parse_constant=_finite_number,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} — сохраните JSON в кодировке UTF-8.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} — ошибка JSON в строке {exc.lineno}, столбец {exc.colno}.") from exc
    except RecursionError as exc:
        raise ValueError(f"{name} — слишком большая вложенность JSON.") from exc
    except ValueError as exc:
        raise ValueError(f"{name} — проверьте ключи и числовые значения в JSON.") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{name} — ожидается объект модуля или урока.")
    if 'module' in data and ('level' in data or isinstance(data['module'], dict)):
        return data
    key = data.get('external_key')
    if isinstance(key, str) and key.strip():
        return data
    raise ValueError(f"{name} — укажите модуль курса или внешний ключ урока external_key.")


def read_content_package(stream: BinaryIO) -> list[dict[str, Any]]:
    """Return package documents in archive order; DB validation belongs to the importer."""
    try:
        with _read_upload(stream) as buffer, ZipFile(buffer) as archive:
            return [
                {'name': member.filename, 'data': _document(archive.read(member), member.filename)}
                for member in _json_members(archive)
            ]
    except (BadZipFile, EOFError, OSError, NotImplementedError, zlib.error, UnicodeDecodeError) as exc:
        raise ValueError("Не удалось прочитать ZIP. Проверьте, что архив не повреждён.") from exc
