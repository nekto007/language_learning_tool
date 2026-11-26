"""Read supported book sources into chapters before opening a publication transaction."""
# ruff: noqa: RUF001 -- validation messages are shown in Russian.

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from docx import Document
from ebooklib import epub
from lxml import etree
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage

from app.admin.services.book_processing_service import BookUploadError, save_uploaded_book_file
from app.books.models import Book, Chapter
from convert_fb2_to_txt import iter_fb2_blocks

_NUMBERED_HEADING = re.compile(
    r'^(?:Chapter|Глава)\s+(?:\d+|[IVXLCDM]+)\b(?:[.\s:–—-].*)?$', re.IGNORECASE,
)
_MARKED_HEADING = re.compile(r'^###\s*CHAPTER_(\d+)\s*(.*)$', re.IGNORECASE)
_GUTENBERG_BOUNDARY = re.compile(r'^\*{3}\s*(START|END) OF (?:THE|THIS) PROJECT GUTENBERG\b', re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_HTML_BLOCKS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'pre', 'div')
_Block = tuple[bool, str]


@dataclass(frozen=True)
class ImportedChapter:
    title: str
    text: str


def _txt_blocks(text: str) -> Iterator[_Block]:
    lines = text.splitlines()
    start = next((index + 1 for index, line in enumerate(lines)
                  if (match := _GUTENBERG_BOUNDARY.match(line.strip())) and match[1].upper() == 'START'), 0)
    paragraph: list[str] = []
    for line in lines[start:]:
        line = line.strip()
        boundary = _GUTENBERG_BOUNDARY.match(line)
        marked = _MARKED_HEADING.fullmatch(line)
        heading = marked is not None or _NUMBERED_HEADING.fullmatch(line) is not None
        if (not line or heading or boundary) and paragraph:
            yield False, '\n'.join(paragraph)
            paragraph.clear()
        if boundary and boundary[1].upper() == 'END':
            break
        if marked:
            yield True, marked[2] or f'Chapter {int(marked[1])}'
        elif heading:
            yield True, line
        elif line:
            paragraph.append(line)
    if paragraph:
        yield False, '\n'.join(paragraph)


def _epub_blocks(path: Path) -> Iterator[_Block]:
    book = epub.read_epub(str(path), options={'ignore_ncx': True})
    metadata_title = next((title for title, _ in book.get_metadata('DC', 'title')), '')
    book_name = re.sub(r'\W+', '', metadata_title.casefold())
    toc: dict[str, set[str]] = defaultdict(set)
    entries = (book.toc,) if isinstance(book.toc, epub.Link) else book.toc or ()
    for entry in entries:
        # Only top-level entries start parts. Nested entries stay in their parent.
        link = entry[0] if isinstance(entry, tuple) else entry
        if href := getattr(link, 'href', None):
            uri = urlsplit(href)
            toc[normpath(unquote(uri.path))].add(unquote(uri.fragment))

    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if linear == 'no' or not isinstance(item, epub.EpubHtml) or isinstance(item, epub.EpubNav):
            continue
        targets = toc.get(normpath(unquote(item.get_name())), set())
        document = BeautifulSoup(item.content, 'html.parser')
        body = document.body or document
        gutenberg_title_page = body.select_one('#pg-header') is not None
        for tag in document.select('nav, script, style, .toc, #pg-header, #pg-footer, #pg-start-separator, #pg-end-separator'):
            tag.decompose()
        for tag in body.find_all('br'):
            tag.replace_with('\v')
        seen_sections: set[int] = set()
        named_part_started = False
        for tag in body.find_all(_HTML_BLOCKS):
            if tag.find(_HTML_BLOCKS) or tag.find_parent(('p', 'li', 'pre')):
                continue
            lines = (' '.join(line.split()) for line in tag.get_text().split('\v'))
            text = '\n\n'.join(line for line in lines if line)
            if not text:
                continue
            if not tag.name.startswith('h'):
                yield False, text
                continue
            title = ' '.join(text.split())
            title_key = re.sub(r'\W+', '', title.casefold())
            if gutenberg_title_page and tag.parent is body and (
                (tag.name == 'h1' and book_name and (title_key == book_name or title_key.startswith(book_name + 'by')))
                or title.casefold().startswith('by ')
                or title.casefold() in ('contents', 'table of contents')
                or (tag.name == 'h4' and re.search(r'\bedition\b', title, re.IGNORECASE))
            ):
                continue
            section = tag.find_parent(class_='chapter')
            if section is None:
                section = next((node for node in (tag, *tag.parents) if node.get('id') in targets), None)
            if section is not None:
                heading = id(section) not in seen_sections
                seen_sections.add(id(section))
            else:
                heading = _NUMBERED_HEADING.fullmatch(title) is not None
                if not named_part_started:
                    heading = heading or tag.name == 'h1' or '' in targets
            named_part_started |= heading
            yield heading, title if heading else text


def _fb2_blocks(path: Path) -> Iterator[_Block]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.parse(str(path), parser).getroot()
    namespace = root.tag.split('}')[0] + '}' if root.tag.startswith('{') else ''
    if root.tag != namespace + 'FictionBook':
        raise ValueError('Файл не является книгой FB2.')
    for body in root.findall(namespace + 'body'):
        if body.get('name') in ('notes', 'footnotes'):
            continue
        for kind, text in iter_fb2_blocks(body, namespace):
            yield kind == 'heading', text


def _source_blocks(path: Path, suffix: str) -> Iterable[_Block]:
    if suffix == '.txt':
        return _txt_blocks(path.read_text(encoding='utf-8-sig'))
    if suffix == '.epub':
        return _epub_blocks(path)
    if suffix == '.fb2':
        return _fb2_blocks(path)
    if suffix == '.docx':
        return ((p.style.name.startswith('Heading'), p.text) for p in Document(path).paragraphs)
    if suffix == '.pdf':
        return _txt_blocks('\n\n'.join(page.extract_text() or '' for page in PdfReader(path).pages))
    raise ValueError('Формат файла не поддерживается.')


def import_chapters(path: Path | None, suffix: str, text: str, title: str) -> list[ImportedChapter]:
    """Use a real chapter for unsectioned text so reader progress has a stable ID."""
    blocks = _source_blocks(path, suffix) if path is not None else _txt_blocks(text)
    chapters: list[ImportedChapter] = []
    paragraphs: list[str] = []
    chapter_title = title
    for heading, block in blocks:
        if '\0' in block:
            raise BookUploadError('Файл содержит недопустимые символы.')
        block = block.strip()
        if not block:
            continue
        if heading:
            if paragraphs:
                chapters.append(ImportedChapter(chapter_title[:255], '\n\n'.join(paragraphs)))
                paragraphs.clear()
            chapter_title = block
        else:
            paragraphs.append(block)
    if paragraphs:
        chapters.append(ImportedChapter(chapter_title[:255], '\n\n'.join(paragraphs)))
    if not chapters or not any(_WORD.search(chapter.text) for chapter in chapters):
        raise BookUploadError('В источнике нет текста для чтения. Загрузите другой файл или вставьте текст.')
    return chapters


def install_chapters(book: Book, chapters: list[ImportedChapter]) -> None:
    """Stage validated chapters and counts, leaving commit and audit to the caller."""
    vocabulary: set[str] = set()
    count = 0
    for number, chapter in enumerate(chapters, 1):
        words = _WORD.findall(chapter.text.lower())
        vocabulary.update(words)
        count += len(words)
        book.chapters.append(Chapter(chap_num=number, title=chapter.title, text_raw=chapter.text, words=len(words)))
    book.chapters_cnt = len(chapters)
    book.words_total = count
    book.unique_words = len(vocabulary)


def prepare_chapters(file: FileStorage | None, text: str, title: str) -> list[ImportedChapter]:
    """Read one optional upload, then remove the source on every outcome."""
    if not file:
        return import_chapters(None, '', text, title)
    temp_path, _, suffix = save_uploaded_book_file(file)
    path = Path(temp_path)
    try:
        return import_chapters(path, suffix, text, title)
    finally:
        path.unlink(missing_ok=True)
