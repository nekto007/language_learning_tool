"""Seed the curated word sets from the 19 hand-made topics.

Only these 19 topics carry real semantic grouping; the other ~3 300 rows in
`topics` hold a single word each and are machine-generated sense labels, so
they are not eligible. A topic that cannot be resolved by name, or that holds
no words, is skipped with a message rather than seeded empty — an empty set
renders a dead card and a quiz route that can only bounce the user back.

Words are ordered by frequency band so a short quiz draws the common words
first (`red`, `blue`) rather than whatever the join happened to return.

Revision ID: 20260815_seed_word_sets
Revises: 20260815_word_sets
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = '20260815_seed_word_sets'
down_revision = '20260815_word_sets'
branch_labels = None
depends_on = None


# (slug, display name, source topic name, emoji, accent, sort_order, description)
# The topic name must match `topics.name` exactly — «Образование (Education)»
# is the curated topic, while «Образование (о человеке, который учится...)» is
# one of the single-word generated rows. Exact matching is what separates them.
_SETS = (
    ('colors', 'Цвета и формы', 'Цвета и визуальные свойства (Colors & Visual Properties)',
     '🎨', 'amber', 10, 'Цвета, оттенки, формы и то, как выглядят вещи.'),
    ('food-drink', 'Еда и напитки', 'Еда и напитки (Food & Drink)',
     '🍽', 'rose', 20, 'Продукты, блюда, напитки и всё, что связано с едой.'),
    ('clothing', 'Одежда и мода', 'Одежда и мода (Clothing & Fashion)',
     '👕', 'violet', 30, 'Одежда, обувь, аксессуары и стиль.'),
    ('animals', 'Животные', 'Животные (Animals)',
     '🐾', 'green', 40, 'Домашние, дикие и морские животные.'),
    ('body-health', 'Тело и здоровье', 'Тело и здоровье (Body & Health)',
     '🫀', 'rose', 50, 'Части тела, самочувствие, медицина.'),
    ('time', 'Время', 'Время (Time)',
     '⏰', 'blue', 60, 'Дни, месяцы, периоды и слова о времени.'),
    ('numbers', 'Числа и измерения', 'Числа и измерения (Numbers & Measurements)',
     '🔢', 'slate', 70, 'Числа, количество, размеры и единицы измерения.'),
    ('nature', 'Природа', 'Природа и окружающая среда (Nature & Environment)',
     '🌿', 'green', 80, 'Погода, растения, ландшафт и экология.'),
    ('transport', 'Транспорт и путешествия', 'Транспорт и путешествия (Transportation & Travel)',
     '✈️', 'teal', 90, 'Транспорт, поездки, дорога и путешествия.'),
    ('places', 'Здания и места', 'Здания и места (Buildings & Places)',
     '🏠', 'amber', 100, 'Дома, городские объекты и места вокруг нас.'),
    ('emotions', 'Эмоции и характер', 'Эмоции и личность (Emotions & Personality)',
     '😊', 'violet', 110, 'Чувства, настроение и черты характера.'),
    ('actions', 'Действия', 'Действия (Actions/Verbs)',
     '🏃', 'indigo', 120, 'Самые нужные глаголы на каждый день.'),
    ('descriptive', 'Описания', 'Описательные слова (Descriptive Words)',
     '✏️', 'slate', 130, 'Прилагательные и слова, которыми описывают предметы.'),
    ('sports', 'Спорт и отдых', 'Спорт и отдых (Sports & Recreation)',
     '⚽', 'teal', 140, 'Виды спорта, игры и свободное время.'),
    ('art-culture', 'Искусство и культура', 'Искусство и культура (Art & Culture)',
     '🎭', 'violet', 150, 'Музыка, кино, литература и искусство.'),
    ('education', 'Образование', 'Образование (Education)',
     '🎓', 'blue', 160, 'Школа, университет, учёба и экзамены.'),
    ('technology', 'Технологии и наука', 'Технологии и наука (Technology & Science)',
     '💻', 'indigo', 170, 'Техника, интернет и научные термины.'),
    ('business', 'Экономика и бизнес', 'Экономика и бизнес (Economy & Business)',
     '💼', 'slate', 180, 'Работа, деньги, компании и торговля.'),
    ('society', 'Политика и общество', 'Правительство и политика (Government & Politics)',
     '🗳', 'blue', 190, 'Государство, законы и общественная жизнь.'),
)


def upgrade():
    conn = op.get_bind()

    seeded = 0
    for slug, name, topic_name, icon, accent, sort_order, description in _SETS:
        existing = conn.execute(
            sa.text('SELECT id FROM word_sets WHERE slug = :slug'), {'slug': slug}
        ).scalar()
        if existing is not None:
            # Re-running must not duplicate or clobber an edited set.
            continue

        topic_id = conn.execute(
            sa.text('SELECT id FROM topics WHERE name = :name'), {'name': topic_name}
        ).scalar()
        if topic_id is None:
            print(f'seed word sets: topic {topic_name!r} not found — skipping set {slug!r}')
            continue

        word_ids = [
            row[0]
            for row in conn.execute(
                sa.text(
                    'SELECT cw.id FROM topic_words tw '
                    'JOIN collection_words cw ON cw.id = tw.word_id '
                    'WHERE tw.topic_id = :tid '
                    "  AND cw.russian_word IS NOT NULL AND cw.russian_word <> '' "
                    'ORDER BY cw.frequency_band NULLS LAST, cw.english_word'
                ),
                {'tid': topic_id},
            ).fetchall()
        ]
        if not word_ids:
            print(f'seed word sets: topic {topic_name!r} has no usable words — skipping {slug!r}')
            continue

        set_id = conn.execute(
            sa.text(
                'INSERT INTO word_sets '
                '(slug, name, description, icon, accent, sort_order, is_published, '
                ' created_at, updated_at) '
                'VALUES (:slug, :name, :description, :icon, :accent, :sort_order, TRUE, '
                '        NOW(), NOW()) '
                'RETURNING id'
            ),
            {
                'slug': slug,
                'name': name,
                'description': description,
                'icon': icon,
                'accent': accent,
                'sort_order': sort_order,
            },
        ).scalar()

        conn.execute(
            sa.text(
                'INSERT INTO word_set_words (set_id, word_id, order_index) '
                'VALUES (:set_id, :word_id, :order_index)'
            ),
            [
                {'set_id': set_id, 'word_id': word_id, 'order_index': index}
                for index, word_id in enumerate(word_ids)
            ],
        )
        seeded += 1

    print(f'seed word sets: created {seeded} of {len(_SETS)} sets')


def downgrade():
    """Remove only the seeded sets, addressed by their slugs.

    NB this cascades into `word_set_quiz_results`: downgrading discards any
    quiz history learners accumulated on these sets. That is inherent to
    removing the sets themselves, not an oversight.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text('DELETE FROM word_sets WHERE slug IN :slugs').bindparams(
            sa.bindparam('slugs', expanding=True)
        ),
        {'slugs': [row[0] for row in _SETS]},
    )
