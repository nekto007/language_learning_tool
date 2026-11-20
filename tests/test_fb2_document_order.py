"""Nested FB2 sections must preserve document order without repeated text."""
import re
from pathlib import Path
import subprocess
import sys

from bs4 import BeautifulSoup
import pytest

from app.books.parsers import parse_fb2
from convert_fb2_to_txt import extract_text_from_fb2


@pytest.fixture(params=['', 'http://www.gribuser.ru/xml/fictionbook/2.0'])
def write_fb2(tmp_path, request):
    def write(body):
        namespace = f' xmlns="{request.param}"' if request.param else ''
        path = tmp_path / 'synthetic.fb2'
        path.write_text(f'<FictionBook{namespace}><body>{body}</body></FictionBook>', encoding='utf-8')
        return str(path)
    return write


def html_blocks(path):
    html, count, unique = parse_fb2(path, 'enhanced')
    soup = BeautifulSoup(html, 'html.parser')
    return [(tag.name, tag.get_text()) for tag in soup.find_all(['h2', 'p'])], count, unique


def converter_blocks(path):
    blocks = []
    for part in re.split(r'\n+', extract_text_from_fb2(path)):
        if part.startswith('### CHAPTER_'):
            blocks.append(('h2', part.split(' ', 2)[2] if len(part.split(' ', 2)) == 3 else ''))
        elif part:
            blocks.append(('p', part))
    return blocks


def test_nested_sections_keep_trailing_parent_text_in_order_once(write_fb2):
    path = write_fb2('<section><title><p>OuterTitle</p></title><p>Alpha.</p>'
                     '<section><title><p>InnerTitle</p></title><p>Beta.</p></section>'
                     '<p>Gamma.</p></section>')
    expected = [('h2', 'OuterTitle'), ('p', 'Alpha.'), ('h2', 'InnerTitle'), ('p', 'Beta.'), ('p', 'Gamma.')]
    blocks, count, unique = html_blocks(path)
    assert blocks == expected
    assert count == unique == 3
    assert converter_blocks(path) == expected


def test_sibling_sections_and_untitled_parent_do_not_steal_nested_heading(write_fb2):
    path = write_fb2('<section><p>Before.</p><section><title><p>First</p></title><p>One.</p></section>'
                     '<p>Between.</p><section><title><p>Second</p></title><p>Two.</p></section>'
                     '<p>After.</p></section>')
    expected = [('p', 'Before.'), ('h2', 'First'), ('p', 'One.'), ('p', 'Between.'),
                ('h2', 'Second'), ('p', 'Two.'), ('p', 'After.')]
    assert html_blocks(path)[0] == expected
    assert converter_blocks(path) == expected


def test_title_paragraphs_merge_once_and_nested_inline_text_is_retained(write_fb2, capsys):
    path = write_fb2('<section><title><p>Main <emphasis>heading</emphasis></p><p>Second line</p></title>'
                     '<p>We <emphasis>read <strong>all</strong> words</emphasis> today.</p></section>')
    expected = [('h2', 'Main heading Second line'), ('p', 'We read all words today.')]
    blocks, count, unique = html_blocks(path)
    assert blocks == expected
    assert count == unique == 5
    assert converter_blocks(path) == expected
    assert capsys.readouterr().out == ''  # No private title/paragraph debug prints.


def test_chapter_number_cleanup_and_markers_remain_compatible(write_fb2):
    path = write_fb2('<section><title><p>1. First</p></title><p>Alpha.</p></section>'
                     '<section><title><p>CHAPTER TWO Next</p></title><p>Beta.</p></section>')
    assert extract_text_from_fb2(path) == '### CHAPTER_01 First\nAlpha.\n### CHAPTER_02 Next\nBeta.'


def test_prefixed_namespace_works_without_duplicate_title_paragraphs(tmp_path):
    path = tmp_path / 'prefixed.fb2'
    path.write_text('<f:FictionBook xmlns:f="http://www.gribuser.ru/xml/fictionbook/2.0"><f:body>'
                    '<f:section><f:title><f:p>Prefixed</f:p></f:title><f:p>Hello.</f:p>'
                    '</f:section></f:body></f:FictionBook>')
    expected = [('h2', 'Prefixed'), ('p', 'Hello.')]
    assert html_blocks(str(path))[0] == expected
    assert converter_blocks(str(path)) == expected


def test_converter_cli_runs_without_site_packages_and_preserves_order(write_fb2, tmp_path):
    path = write_fb2('<section><title><p>Outer</p></title><p>Before.</p>'
                     '<section><title><p>Inner</p></title><p>Inside.</p></section>'
                     '<p>After.</p></section>')
    output = tmp_path / 'converted.txt'
    converter = Path(__file__).resolve().parents[1] / 'convert_fb2_to_txt.py'
    result = subprocess.run([sys.executable, '-S', str(converter), path, str(output)],
                            check=False, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == '### CHAPTER_01 Outer\nBefore.\n### CHAPTER_02 Inner\nInside.\n\nAfter.'
