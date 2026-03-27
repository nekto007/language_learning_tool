from flask import render_template, abort
from flask_login import current_user

from app.grammar_public import grammar_public_bp
from app.grammar_lab.models import GrammarTopic


@grammar_public_bp.route('/')
def index():
    """Public grammar catalog — all levels and topics."""
    topics = GrammarTopic.query.order_by(GrammarTopic.level, GrammarTopic.order).all()

    # Group by level
    levels_order = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    grouped: dict[str, list] = {lvl: [] for lvl in levels_order}
    for t in topics:
        if t.level in grouped:
            grouped[t.level].append(t)

    # Remove empty levels
    grouped = {lvl: items for lvl, items in grouped.items() if items}

    return render_template('grammar_public/index.html', grouped=grouped)


@grammar_public_bp.route('/<slug>')
def topic(slug: str):
    """Public topic page with full theory, no exercises."""
    topic_obj = GrammarTopic.query.filter_by(slug=slug).first_or_404()
    topic_data = topic_obj.to_dict(include_content=True)
    topic_data['exercise_count'] = topic_obj.exercise_count

    # Load related topics
    related = []
    related_slugs = (topic_obj.content or {}).get('related_topics', [])
    if related_slugs:
        related_objs = GrammarTopic.query.filter(GrammarTopic.slug.in_(related_slugs)).all()
        related = [r.to_dict() for r in related_objs]

    # SEO description from introduction
    intro = (topic_obj.content or {}).get('introduction', '')
    meta_description = intro[:150].rstrip() if intro else f'{topic_obj.title} — правила, примеры, таблицы.'
    if topic_data['exercise_count']:
        meta_description += f' {topic_data["exercise_count"]} упражнений для практики.'

    is_authenticated = current_user.is_authenticated

    return render_template(
        'grammar_public/topic.html',
        topic=topic_data,
        related=related,
        meta_description=meta_description,
        is_authenticated=is_authenticated,
    )
