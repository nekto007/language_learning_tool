"""Regression test for UI-002 (cross-zone audit 2026-08-08).

Jinja silently discards a ``{% block %}`` whose name the parent template does
not declare. Two admin pages put all of their JavaScript in ``{% block extra_js %}``
while ``admin/base.html`` declared only ``scripts`` — so every ``onclick`` on
those pages raised ``ReferenceError`` and the editors were unusable.

This walks the whole template tree instead of pinning the two known files: any
child whose *top-level* block name is unknown to its ancestor chain is a dead
block. Blocks nested inside another block are exempt — that is how the lesson
bases hand extension points down to their own children.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import nodes

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / 'app' / 'templates'


def _parse(env, template_name: str):
    path = TEMPLATE_ROOT / template_name
    if not path.is_file():
        return None
    return env.parse(path.read_text(encoding='utf-8'), filename=template_name)


def _parent_of(ast) -> str | None:
    for node in ast.find_all(nodes.Extends):
        if isinstance(node.template, nodes.Const) and isinstance(node.template.value, str):
            return node.template.value
        return None  # dynamic extends — nothing static to check against
    return None


def _declared_blocks(env, template_name: str, _seen: frozenset[str] = frozenset()) -> set[str]:
    """Every block name a template offers, including the ones it inherits."""
    if template_name in _seen:
        return set()
    ast = _parse(env, template_name)
    if ast is None:
        return set()
    names = {node.name for node in ast.find_all(nodes.Block)}
    parent = _parent_of(ast)
    if parent:
        names |= _declared_blocks(env, parent, _seen | {template_name})
    return names


def _top_level_blocks(ast) -> list[str]:
    return [node.name for node in ast.body if isinstance(node, nodes.Block)]


@pytest.fixture
def jinja_env(app):
    return app.jinja_env


@pytest.mark.smoke
def test_admin_base_declares_extra_js(jinja_env):
    assert 'extra_js' in _declared_blocks(jinja_env, 'admin/base.html')


def test_every_template_parses(jinja_env):
    """A template that cannot be parsed is a guaranteed 500 wherever it is used."""
    from jinja2 import TemplateSyntaxError

    broken = []
    for path in sorted(TEMPLATE_ROOT.rglob('*.html')):
        try:
            _parse(jinja_env, str(path.relative_to(TEMPLATE_ROOT)))
        except TemplateSyntaxError as exc:
            broken.append(f'{path.relative_to(TEMPLATE_ROOT)}: {exc}')

    assert not broken, 'Templates with syntax errors:\n' + '\n'.join(broken)


def test_no_template_defines_a_block_its_parent_ignores(jinja_env):
    orphans = []
    checked = 0

    for path in sorted(TEMPLATE_ROOT.rglob('*.html')):
        name = str(path.relative_to(TEMPLATE_ROOT))
        ast = _parse(jinja_env, name)
        if ast is None:
            continue
        parent = _parent_of(ast)
        if not parent:
            continue
        available = _declared_blocks(jinja_env, parent)
        if not available:
            continue
        checked += 1
        for block in _top_level_blocks(ast):
            if block not in available:
                orphans.append(f'{name}: {{% block {block} %}} is not declared by {parent}')

    assert checked > 100, f'only {checked} templates inspected — the walk broke'
    assert not orphans, 'Blocks silently dropped by Jinja:\n' + '\n'.join(sorted(orphans))
