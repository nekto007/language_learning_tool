# app/admin/routes/word_set_routes.py

"""Admin management of curated themed word sets.

Sets are the learner-facing catalogue («Цвета», «Одежда»). Their membership is
editorial, so everything that changes a set lives here rather than in the study
blueprint. Every mutating route is wrapped in ``admin_audit_required`` — the
coverage test derives its route list from the live URL map, so an unaudited
mutation fails the suite rather than slipping through.
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from app.admin.utils.decorators import admin_audit_required, admin_required
from app.admin.utils.request_validators import escape_like
from app.study.models import WORD_SET_ACCENTS, WordSet, WordSetWord
from app.utils.db import db
from app.words.models import CollectionWords

word_set_bp = Blueprint('word_set_admin', __name__)

logger = logging.getLogger(__name__)


# Cyrillic → Latin, so a set named «Цвета и формы» proposes `cveta-i-formy`
# instead of an empty slug. Deliberately hand-rolled: the project has no
# transliteration dependency, and pulling one in for a single admin
# convenience is not worth the supply-chain surface.
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def _slugify(raw: str) -> str:
    """Reduce a name to an ASCII slug usable in a URL.

    May legitimately return '' (a name of only punctuation or unsupported
    script); callers must handle that rather than persist an empty slug.
    """
    import re

    lowered = (raw or '').lower()
    slug = ''.join(_TRANSLIT.get(char, char) for char in lowered)
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return slug[:80]


def _slug_taken(slug: str, exclude_id: int | None = None) -> bool:
    query = WordSet.query.filter(WordSet.slug == slug)
    if exclude_id is not None:
        query = query.filter(WordSet.id != exclude_id)
    return db.session.query(query.exists()).scalar()


def _read_form(form) -> dict:
    accent = (form.get('accent') or '').strip()
    return {
        'name': (form.get('name') or '').strip(),
        'slug': (form.get('slug') or '').strip(),
        'description': (form.get('description') or '').strip() or None,
        'icon': (form.get('icon') or '').strip() or None,
        'accent': accent if accent in WORD_SET_ACCENTS else WORD_SET_ACCENTS[0],
        'level': (form.get('level') or '').strip() or None,
        'sort_order': _int_or_zero(form.get('sort_order')),
        'is_published': bool(form.get('is_published')),
    }


def _int_or_zero(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


@word_set_bp.route('/word-sets')
@admin_required
def word_set_list():
    """All sets with their word counts, in one grouped query."""
    counts = dict(
        db.session.query(WordSetWord.set_id, db.func.count(WordSetWord.id))
        .group_by(WordSetWord.set_id)
        .all()
    )
    sets = WordSet.query.order_by(WordSet.sort_order, WordSet.name).all()
    return render_template(
        'admin/word_sets/list.html',
        word_sets=sets,
        counts=counts,
    )


@word_set_bp.route('/word-sets/create', methods=['GET', 'POST'])
@admin_audit_required('word_set.create', target_type='word_set')
def word_set_create():
    if request.method == 'POST':
        data = _read_form(request.form)
        if not data['name']:
            flash('Название обязательно', 'danger')
            return render_template(
                'admin/word_sets/form.html', word_set=None, accents=WORD_SET_ACCENTS, data=data
            ), 400

        slug = data['slug'] or _slugify(data['name'])
        if not slug:
            flash('Не удалось построить слаг — задайте его вручную', 'danger')
            return render_template(
                'admin/word_sets/form.html', word_set=None, accents=WORD_SET_ACCENTS, data=data
            ), 400
        if _slug_taken(slug):
            flash(f'Слаг «{slug}» уже занят', 'danger')
            return render_template(
                'admin/word_sets/form.html', word_set=None, accents=WORD_SET_ACCENTS, data=data
            ), 400

        word_set = WordSet(
            slug=slug,
            name=data['name'],
            description=data['description'],
            icon=data['icon'],
            accent=data['accent'],
            level=data['level'],
            sort_order=data['sort_order'],
            is_published=data['is_published'],
        )
        db.session.add(word_set)
        db.session.commit()
        flash(f'Набор «{word_set.name}» создан', 'success')
        return redirect(url_for('word_set_admin.word_set_words', set_id=word_set.id))

    return render_template(
        'admin/word_sets/form.html', word_set=None, accents=WORD_SET_ACCENTS, data=None
    )


@word_set_bp.route('/word-sets/<int:set_id>/edit', methods=['GET', 'POST'])
@admin_audit_required('word_set.update', target_type='word_set', target_id_arg='set_id')
def word_set_edit(set_id):
    word_set = WordSet.query.get_or_404(set_id)

    if request.method == 'POST':
        data = _read_form(request.form)
        if not data['name']:
            flash('Название обязательно', 'danger')
            return render_template(
                'admin/word_sets/form.html', word_set=word_set,
                accents=WORD_SET_ACCENTS, data=data,
            ), 400

        slug = data['slug'] or word_set.slug
        if _slug_taken(slug, exclude_id=word_set.id):
            flash(f'Слаг «{slug}» уже занят', 'danger')
            return render_template(
                'admin/word_sets/form.html', word_set=word_set,
                accents=WORD_SET_ACCENTS, data=data,
            ), 400

        word_set.slug = slug
        word_set.name = data['name']
        word_set.description = data['description']
        word_set.icon = data['icon']
        word_set.accent = data['accent']
        word_set.level = data['level']
        word_set.sort_order = data['sort_order']
        word_set.is_published = data['is_published']
        db.session.commit()
        flash('Набор обновлён', 'success')
        return redirect(url_for('word_set_admin.word_set_list'))

    return render_template(
        'admin/word_sets/form.html', word_set=word_set, accents=WORD_SET_ACCENTS, data=None
    )


@word_set_bp.route('/word-sets/<int:set_id>/delete', methods=['POST'])
@admin_audit_required('word_set.delete', target_type='word_set', target_id_arg='set_id')
def word_set_delete(set_id):
    word_set = WordSet.query.get_or_404(set_id)
    name = word_set.name
    db.session.delete(word_set)
    db.session.commit()
    flash(f'Набор «{name}» удалён', 'success')
    return redirect(url_for('word_set_admin.word_set_list'))


@word_set_bp.route('/word-sets/<int:set_id>/words')
@admin_required
def word_set_words(set_id):
    """Membership editor for one set."""
    word_set = WordSet.query.get_or_404(set_id)
    entries = (
        db.session.query(WordSetWord, CollectionWords)
        .join(CollectionWords, CollectionWords.id == WordSetWord.word_id)
        .filter(WordSetWord.set_id == set_id)
        .order_by(WordSetWord.order_index, CollectionWords.english_word)
        .all()
    )
    return render_template(
        'admin/word_sets/words.html',
        word_set=word_set,
        entries=entries,
    )


@word_set_bp.route('/word-sets/<int:set_id>/words/add', methods=['POST'])
@admin_audit_required('word_set.add_word', target_type='word_set', target_id_arg='set_id')
def word_set_add_word(set_id):
    word_set = WordSet.query.get_or_404(set_id)
    word_id = _int_or_zero(request.form.get('word_id'))

    word = CollectionWords.query.get(word_id) if word_id else None
    if word is None:
        flash('Слово не найдено', 'danger')
        return redirect(url_for('word_set_admin.word_set_words', set_id=set_id))

    already = db.session.query(
        db.session.query(WordSetWord.id)
        .filter(WordSetWord.set_id == set_id, WordSetWord.word_id == word_id)
        .exists()
    ).scalar()
    if already:
        flash(f'«{word.english_word}» уже в наборе', 'info')
        return redirect(url_for('word_set_admin.word_set_words', set_id=set_id))

    next_index = (
        db.session.query(db.func.coalesce(db.func.max(WordSetWord.order_index), -1))
        .filter(WordSetWord.set_id == set_id)
        .scalar()
    ) + 1

    db.session.add(WordSetWord(set_id=word_set.id, word_id=word.id, order_index=next_index))
    db.session.commit()
    flash(f'«{word.english_word}» добавлено', 'success')
    return redirect(url_for('word_set_admin.word_set_words', set_id=set_id))


@word_set_bp.route('/word-sets/<int:set_id>/words/<int:word_id>/remove', methods=['POST'])
@admin_audit_required('word_set.remove_word', target_type='word_set', target_id_arg='set_id')
def word_set_remove_word(set_id, word_id):
    WordSet.query.get_or_404(set_id)
    entry = WordSetWord.query.filter_by(set_id=set_id, word_id=word_id).first()
    if entry is not None:
        db.session.delete(entry)
        db.session.commit()
        flash('Слово убрано из набора', 'success')
    return redirect(url_for('word_set_admin.word_set_words', set_id=set_id))


@word_set_bp.route('/word-sets/api/word-search')
@admin_required
def word_set_word_search():
    """Autocomplete for the membership editor.

    Its own URL rather than a second handler on an existing search path: the
    /admin namespace is shared by many blueprints, and two rules on one URL are
    resolved by registration order, which once cost the deck editor half its
    dictionary.
    """
    term = (request.args.get('q') or '').strip()
    if len(term) < 2:
        return jsonify({'results': []})

    # escape_like plus the escape character — without the second argument the
    # escaping does not take effect and `_`/`%` from user input act as
    # wildcards.
    pattern = f'{escape_like(term)}%'
    words = (
        CollectionWords.query
        .filter(CollectionWords.english_word.ilike(pattern, escape='\\'))
        .order_by(CollectionWords.english_word)
        .limit(20)
        .all()
    )
    return jsonify({
        'results': [
            {'id': w.id, 'english_word': w.english_word, 'russian_word': w.russian_word}
            for w in words
        ]
    })
