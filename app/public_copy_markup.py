"""Locate and replace editorial fields in the rendered, original public HTML."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from html import escape, unescape
from html.parser import HTMLParser

from bs4 import BeautifulSoup, Tag
from jinja2.utils import htmlsafe_json_dumps

_VOID = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'))
_META = (
    ('seo.description', 'Описание страницы', 'meta[name="description"]'),
    ('seo.og_title', 'Заголовок для социальных сетей', 'meta[property="og:title"]'),
    ('seo.og_description', 'Описание для социальных сетей', 'meta[property="og:description"]'),
)
_SEARCH = 'Заголовок и описание для поиска'


class LayoutMismatch(ValueError):
    """The published address map no longer matches its source template."""


def digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@dataclass
class Element:
    start: int
    body: int
    close: int
    end: int


class _Offsets(HTMLParser):
    """Source ranges for selected elements, without serializing the DOM again."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=False)
        self.lines = [0, *(match.end() for match in re.finditer('\n', html))]
        self.elements: dict[tuple[int, int], Element] = {}
        self.stack: list[tuple[str, Element]] = []
        self.html = html
        self.feed(html)
        self.close()

    def _start(self, tag: str, *, empty: bool) -> None:
        position = self.getpos()
        start = self.lines[position[0] - 1] + position[1]
        body = start + len(self.get_starttag_text())
        element = self.elements[position] = Element(start, body, body, body)
        if not empty and tag not in _VOID:
            self.stack.append((tag, element))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, empty=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, empty=True)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            name, element = self.stack[index]
            if name == tag:
                line, column = self.getpos()
                element.close = self.lines[line - 1] + column
                element.end = self.html.index('>', element.close) + 1
                del self.stack[index:]
                break


@dataclass(frozen=True)
class Field:
    start: int
    end: int
    label: str
    value: str


class _Markup:
    def __init__(self, html: str) -> None:
        self.html = html
        self.dom = BeautifulSoup(html, 'html.parser')
        self.offsets = _Offsets(html).elements

    def element(self, tag: Tag) -> Element:
        try:
            return self.offsets[tag.sourceline, tag.sourcepos]
        except KeyError as exc:
            raise LayoutMismatch('unmapped element') from exc

    def one(self, selector: str) -> Tag:
        selected = self.dom.select(selector)
        if len(selected) != 1:
            raise LayoutMismatch(f'expected one match for {selector}')
        return selected[0]

    def _field(self, start: int, end: int, label: str) -> Field | None:
        match = re.fullmatch(r'(\s*)(.*?)(\s*)', self.html[start:end], re.S)
        value = unescape(match[2])
        if not re.search(r'[^\W\d_]', value):
            return None
        if '<' in match[2]:
            raise LayoutMismatch('unexpected markup inside an editorial text field')
        return Field(start + len(match[1]), end - len(match[3]), label, value)

    def fields(self, tag: Tag, *, inline_links: bool = False, number_prefix: bool = False) -> list[Field]:
        part = self.element(tag)
        label = ('Подпись ссылки' if tag.name == 'a' else 'Подпись кнопки' if tag.name == 'button'
                 else 'Заголовок' if tag.name in ('h1', 'h2', 'h3') else 'Текст')
        position = part.body
        result = []
        for child in tag.find_all(recursive=False):
            child_element = self.element(child)
            field = self._field(position, child_element.start, label)
            if field:
                result.append(field)
            if inline_links and child.name == 'a':
                result.extend(self.fields(child))
            position = child_element.end
        if number_prefix:
            prefix = re.match(r'\s*\d+', self.html[position:part.close])
            if not prefix:
                raise LayoutMismatch('missing counter')
            position += prefix.end()
        field = self._field(position, part.close, label)
        if field:
            result.append(field)
        return result

    def selected_fields(self, selector: str) -> list[Field]:
        return [field for tag in self.dom.select(selector) for field in self.fields(tag)]

    def seo_fields(self, page: str) -> dict[str, Field]:
        title = self.element(self.one('head > title'))
        fields = {'seo.title': Field(title.body, title.close, 'Заголовок страницы',
                                     unescape(self.html[title.body:title.close]))}
        for key, label, selector in _META if page == 'home' else _META[:1]:
            meta = self.element(self.one(f'head > {selector}'))
            found = re.search(r'\bcontent\s*=\s*(["\'])(.*?)\1', self.html[meta.start:meta.end], re.S)
            if not found:
                raise LayoutMismatch('missing meta content')
            start, end = found.span(2)
            fields[key] = Field(meta.start + start, meta.start + end, label, unescape(found[2]))
        return fields


def _group(fields: Iterable[Field], slot: int, indices: Iterable[int]) -> dict[str, Field]:
    fields, indices = list(fields), list(indices)
    if len(fields) != len(indices):
        raise LayoutMismatch(f'wrong number of fields in group {slot}')
    return {f'{slot}.{index}': field for index, field in zip(indices, fields, strict=True)}


def _home_groups(markup: _Markup) -> dict[str, dict[str, Field]]:
    out = {}
    select = markup.selected_fields
    hero = select('.land-hero__title, .land-hero__desc, #placement-conditions, .land-hero__actions > a')
    direct = markup.fields(markup.one('.land-hero__direct'), inline_links=True)
    guest = len(direct) == 2
    out['Первый экран'] = _group([*hero, *direct], 1, [1, 2, 3, 4, 5, 6, 8, 9] if guest else range(1, 8))
    title = select('#try-english > h2, #try-english > p, #try-english #preview-reset')
    noscript = markup.fields(markup.one('#landing-preview noscript > p'))
    if len(noscript) != 2:
        raise LayoutMismatch('preview answer label moved')
    out['Пример задания'] = _group(
        [*title, noscript[0], *select('#try-english :is(.land-preview__next, #preview-register, .land-preview__note)')],
        2, range(1, 8),
    )
    stats = markup.dom.select('.land-stats__item')
    out['Статистика'] = _group(
        [field for index, el in enumerate(stats) for field in markup.fields(el, number_prefix=index < 2)],
        3, range(1, 4),
    )
    for label, slot, count, selector in (
        ('Возможности', 4, 10, '.land-features > h2, .land-features > p, .land-feature__title, .land-feature__desc'),
        ('Как это работает', 5, 10, '.land-how > h2, .land-how > p, .land-how .land-step__title, .land-how .land-step__desc'),
        ('Уровни обучения', 6, 12, '.land-levels > h2, .land-levels > p, .land-level__code, .land-level__name'),
        ('Первая неделя', 7, 8, '.land-start > h2, .land-start > p, .land-start .land-step__title, .land-start .land-step__desc'),
        ('Поделиться', 8, 5, '.land-share > h2, .land-share > p, .land-share label, #landing-share-copy'),
        ('Частые вопросы', 9, 2, '.land-faq > h2, .land-faq > p'),
    ):
        out[label] = _group(select(selector), slot, range(1, count + 1))
    if markup.dom.select_one('.land-wotd'):
        audio = bool(markup.dom.select_one('.land-wotd .land-audio-btn'))
        out['Слово дня'] = _group(
            select('.land-wotd > h2, .land-wotd .land-audio-btn, .land-wod-cta'), 10, [1, 2, 3] if audio else [1, 3],
        )
    out['Интеграция Google'] = _group(
        [field for tag in markup.dom.select('#google-integration > :is(h2,p)')
         for field in markup.fields(tag, inline_links=True)], 11, range(1, 7),
    )
    out['Последний блок'] = _group(select('.land-cta > h2, .land-cta > p, .land-cta > a'), 12, [1, 2, 4 if guest else 3])
    return out


_LEGAL_LAYOUT = {
    'support': (4, 2, 2, 2, 9),
    'privacy': (2, 3, 4, 23, 3, 4, 3, 2, 9, 4, 10, 2),
}


def _legal_groups(markup: _Markup, page: str) -> dict[str, dict[str, Field]]:
    article = markup.one('article.legal-page')
    groups: list[tuple[str, list[Field]]] = [('Заголовок страницы', [])]
    for tag in article.find_all(('h1', 'h2', 'h3', 'p'), recursive=False):
        if tag.name == 'h2':
            groups.append((tag.get_text(strip=True), []))
        groups[-1][1].extend(markup.fields(tag, inline_links=True))
    if len(groups) != len(_LEGAL_LAYOUT[page]):
        raise LayoutMismatch('wrong number of legal sections')
    return {label: _group(fields, slot, range(1, count + 1))
            for slot, ((label, fields), count) in enumerate(zip(groups, _LEGAL_LAYOUT[page], strict=True), 1)}


def _fields(markup: _Markup, page: str) -> dict[str, dict[str, Field]]:
    groups = _home_groups(markup) if page == 'home' else _legal_groups(markup, page)
    return {**groups, _SEARCH: markup.seo_fields(page)}


def _faq(markup: _Markup) -> tuple[list[list[str]], list[Tag], Tag]:
    details = markup.dom.select('.land-faq__list > details.land-faq__item')
    scripts = [(tag, json.loads(tag.string)) for tag in markup.dom.select('script[type="application/ld+json"]')]
    candidate = [(tag, data) for tag, data in scripts if isinstance(data, dict) and data.get('@type') == 'FAQPage']
    if not details or len(candidate) != 1:
        raise LayoutMismatch('missing FAQ or structured data')
    tag, data = candidate[0]
    if any(node.summary is None or node.div is None for node in details):
        raise LayoutMismatch('missing FAQ question or answer element')
    list_items = [[node.summary.get_text(strip=True), node.div.get_text(strip=True)] for node in details]
    if list_items != [[row['name'], row['acceptedAnswer']['text']] for row in data['mainEntity']]:
        raise LayoutMismatch('FAQ and structured data disagree')
    return list_items, details, tag


def editable_defaults(page: str, *originals: str) -> tuple[dict, dict[str, list[tuple[str, str]]]]:
    groups: dict[str, dict[str, str]] = {}
    values = {}
    faq = None
    for original in originals:
        markup = _Markup(original)
        for name, fields in _fields(markup, page).items():
            groups.setdefault(name, {}).update({key: field.label for key, field in fields.items()})
            values.update({key: field.value for key, field in fields.items()})
        if page == 'home':
            faq = _faq(markup)[0]
    ordered = {name: sorted(fields.items(), key=lambda row: int(row[0].split('.')[1]))
               if name != _SEARCH else list(fields.items()) for name, fields in groups.items()}
    return ({'text': values, **({'faq': faq} if faq is not None else {})}, ordered)


def _patch(html: str, edits: list[tuple[int, int, str]]) -> str:
    pieces = []
    previous = 0
    for start, end, value in sorted(edits):
        if not previous <= start <= end <= len(html):
            raise LayoutMismatch('overlapping editorial addresses')
        pieces.extend((html[previous:start], value))
        previous = end
    pieces.append(html[previous:])
    return ''.join(pieces)


def _faq_edits(markup: _Markup, pairs: list[list[str]], expected: str | None) -> list[tuple[int, int, str]]:
    old, details, script = _faq(markup)
    if expected is not None and expected != digest(old):
        raise LayoutMismatch('original FAQ changed')
    if pairs == old:
        return []
    first, last = markup.element(details[0]), markup.element(details[-1])
    question, = markup.fields(details[0].summary)
    answer, = markup.fields(details[0].div)
    html = markup.html[first.start:first.end]
    new = [
        _patch(html, [(field.start - first.start, field.end - first.start, escape(text))
                      for field, text in ((question, q), (answer, a))])
        for q, a in pairs
    ]
    schema = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in pairs],
    }
    structured = markup.element(script)
    return [(first.start, last.end, '\n'.join(new)),
            (structured.body, structured.close, str(htmlsafe_json_dumps(schema, ensure_ascii=False)))]


def apply_copy(page: str, html: str, overrides: dict) -> str:
    """Patch only addressed source ranges, keeping the rest of this response intact."""
    markup = _Markup(html)
    edits = []
    expected = overrides.get('base', {})
    for fields in _fields(markup, page).values():
        for key, field in fields.items():
            if (value := overrides['text'].get(key)) is None:
                continue
            if key in expected and expected[key] != digest(field.value):
                raise LayoutMismatch(f'original field changed at {key}')
            if value != field.value:
                edits.append((field.start, field.end, escape(value)))
    if page == 'home' and 'faq' in overrides:
        edits.extend(_faq_edits(markup, overrides['faq'], expected.get('faq')))
    return _patch(html, edits)
