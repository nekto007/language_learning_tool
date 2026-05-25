"""Presentation helpers for word detail pages."""

from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.words.models import Collection, CollectionWords, Topic

_SEMANTIC_GROUPS = {
    'люди и роли': {
        'adult', 'baby', 'boy', 'child', 'children', 'classmate', 'colleague',
        'dad', 'daughter', 'father', 'friend', 'girl', 'grandfather',
        'grandmother', 'man', 'mother', 'mum', 'parent', 'person', 'people',
        'pupil', 'sister', 'student', 'teacher', 'teenager', 'woman',
    },
    'приветствия': {
        'bye', 'farewell', 'good afternoon', 'good evening', 'good morning',
        'good night', 'goodbye', 'hello', 'hi', 'see you',
    },
    'учеба': {
        'book', 'class', 'classroom', 'course', 'desk', 'homework', 'lesson',
        'notebook', 'pencil', 'school', 'study', 'teacher', 'student',
    },
}
_EMPTY_TEXT_VALUES = {'', 'null', 'none', 'undefined', 'nan', '[]', '{}', '-'}
_ARTICLE_ROLE_NOUNS = _SEMANTIC_GROUPS['люди и роли']
_DIRECTION_LABELS = {
    'eng-rus': 'EN → RU',
    'rus-eng': 'RU → EN',
}
_STATE_LABELS = {
    'new': 'Новая',
    'learning': 'Изучение',
    'review': 'Повторение',
    'relearning': 'Повторное закрепление',
}


def normalise_word_list(value) -> list[str]:
    """Return a clean list for JSON list fields such as synonyms/antonyms."""
    if not value:
        return []
    if isinstance(value, str):
        raw_items = value.replace(';', ',').split(',')
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return []
    clean_items = []
    for item in raw_items:
        text = _clean_optional_text(item)
        if text:
            clean_items.append(text)
    return clean_items


def _clean_optional_text(value) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() in _EMPTY_TEXT_VALUES else text


def _normalise_lookup(value: str) -> str:
    return (value or '').strip().lower()


def _semantic_group_labels(value: str) -> set[str]:
    lookup = _normalise_lookup(value).replace('-', ' ')
    tokens = set(lookup.split())
    labels = set()
    for label, terms in _SEMANTIC_GROUPS.items():
        if lookup in terms or tokens.intersection(terms):
            labels.add(label)
    return labels


def frequency_band_label(band) -> str:
    labels = {
        1: 'Top 1000',
        2: 'Top 3000',
        3: 'Top 10000',
    }
    return labels.get(band, 'Не указана')


def _plural_days(days: int) -> str:
    days = abs(int(days))
    if 11 <= days % 100 <= 14:
        suffix = 'дней'
    elif days % 10 == 1:
        suffix = 'день'
    elif 2 <= days % 10 <= 4:
        suffix = 'дня'
    else:
        suffix = 'дней'
    return f'{days} {suffix}'


def _to_naive_utc(value):
    if value is None:
        return None
    if getattr(value, 'tzinfo', None) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _format_review_time(value, now: datetime) -> str:
    review_at = _to_naive_utc(value)
    if review_at is None:
        return 'не запланировано'
    if review_at <= now:
        return 'сейчас'
    today = now.date()
    review_date = review_at.date()
    day_delta = (review_date - today).days
    if day_delta == 0:
        return 'сегодня'
    if day_delta == 1:
        return 'завтра'
    if 1 < day_delta <= 6:
        return f'через {_plural_days(day_delta)}'
    return review_at.strftime('%d.%m.%Y')


def _direction_accuracy(correct: int, incorrect: int) -> int:
    total = correct + incorrect
    return round(correct * 100 / total) if total else 0


def item_type_label(item_type: str | None) -> str:
    labels = {
        'word': 'Слово',
        'phrasal_verb': 'Фразовый глагол',
    }
    return labels.get(item_type or 'word', item_type or 'Слово')


def _build_article_mistake(word: CollectionWords) -> dict | None:
    english = _normalise_lookup(word.english_word)
    if english not in _ARTICLE_ROLE_NOUNS:
        return None

    article = 'an' if english[0] in 'aeiou' else 'a'
    return {
        'title': 'Частая ошибка',
        'wrong': f'I am {english}.',
        'correct': f'I am {article} {english}.',
    }


def build_word_profile(word: CollectionWords) -> dict:
    """Prepare all user-facing collection_words fields for word detail pages."""
    synonyms = normalise_word_list(word.synonyms)
    antonyms = normalise_word_list(word.antonyms)
    usage_context = _clean_optional_text(word.usage_context)
    etymology = _clean_optional_text(word.etymology)
    phrasal_verbs = sorted(
        list(getattr(word, 'phrasal_verbs', []) or []),
        key=lambda item: ((item.frequency_rank or 999999), item.english_word or ''),
    )
    audio_available = bool(word.get_download and word.listening)

    admin_facts = [
        {'label': 'ID', 'value': word.id},
        {'label': 'Тип', 'value': item_type_label(word.item_type)},
        {'label': 'Brown corpus', 'value': 'Да' if word.brown else 'Нет'},
        {'label': 'Аудио', 'value': 'Есть' if audio_available else 'Нет'},
    ]
    if word.level:
        admin_facts.insert(2, {'label': 'Уровень', 'value': word.level})
    if word.frequency_rank:
        admin_facts.insert(3, {'label': 'Частотность', 'value': f'#{word.frequency_rank}'})
    if word.frequency_band:
        admin_facts.insert(4, {'label': 'Частотная группа', 'value': frequency_band_label(word.frequency_band)})

    book_count = len(getattr(word, 'books', []) or [])
    study_facts = []
    if word.level:
        study_facts.append({'label': 'Уровень', 'value': word.level})
    if word.frequency_band:
        study_facts.append({'label': 'Частотная группа', 'value': frequency_band_label(word.frequency_band)})
    if audio_available:
        study_facts.append({'label': 'Аудио', 'value': 'Есть'})
    if book_count:
        study_facts.append({'label': 'Встречается в книгах', 'value': str(book_count)})

    public_facts = []
    if word.level:
        public_facts.append({'label': 'Уровень', 'value': word.level})
    if word.frequency_band:
        public_facts.append({'label': 'Частотная группа', 'value': frequency_band_label(word.frequency_band)})
    if audio_available:
        public_facts.append({'label': 'Аудио', 'value': 'Есть'})

    return {
        'synonyms': synonyms,
        'antonyms': antonyms,
        'usage_context': usage_context,
        'etymology': etymology,
        'frequency_band_label': frequency_band_label(word.frequency_band),
        'item_type_label': item_type_label(word.item_type),
        'audio_available': audio_available,
        'facts': admin_facts,
        'admin_facts': admin_facts,
        'study_facts': study_facts,
        'public_facts': public_facts,
        'base_word': word.base_word,
        'phrasal_verbs': phrasal_verbs[:8],
        'common_mistake': _build_article_mistake(word),
    }


def build_word_study_summary(user_word) -> dict:
    """Build an action-oriented SRS summary for the private word page."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not user_word:
        return {
            'status': 'new',
            'status_css': 'new',
            'status_label': 'Новое слово',
            'status_description': 'Добавьте слово в изучение, чтобы появились повторения.',
            'badge_label': 'Новое',
            'primary_action_label': 'Изучать',
            'primary_action_kind': 'set_learning',
            'primary_action_extra_study': False,
            'secondary_action_label': None,
            'next_review_label': 'не запланировано',
            'accuracy_label': '0%',
            'correct_total': 0,
            'incorrect_total': 0,
            'repetitions_total': 0,
            'lapses_total': 0,
            'interval_label': 'нет',
            'has_directions': False,
            'directions': [],
        }

    directions = sorted(
        user_word.directions.all(),
        key=lambda item: {'eng-rus': 0, 'rus-eng': 1}.get(item.direction, 9),
    )
    is_mastered = user_word.is_mastered
    status = 'mastered' if is_mastered else (user_word.status or 'new')
    status_labels = {
        'new': 'Новое слово',
        'learning': 'Изучается',
        'review': 'На повторении',
        'mastered': 'Выученное слово',
    }
    descriptions = {
        'new': 'Карточки созданы, но слово еще не отвечалось.',
        'learning': 'Слово закрепляется короткими повторениями.',
        'review': 'Слово уже в интервальном повторении.',
        'mastered': 'Слово держится на длинном интервале.',
    }
    badge_labels = {
        'new': 'Новое',
        'learning': 'Изучается',
        'review': 'Повторение',
        'mastered': 'Выучено',
    }

    correct_total = sum(direction.correct_count or 0 for direction in directions)
    incorrect_total = sum(direction.incorrect_count or 0 for direction in directions)
    repetitions_total = sum(direction.repetitions or 0 for direction in directions)
    lapses_total = sum(direction.lapses or 0 for direction in directions)
    interval_values = [direction.interval or 0 for direction in directions if direction.interval is not None]
    interval_label = f'{min(interval_values)} дн.' if interval_values else 'нет'
    next_values = [
        _to_naive_utc(direction.next_review)
        for direction in directions
        if direction.next_review is not None
    ]
    next_review_at = min(next_values) if next_values else None
    is_due_now = bool(next_review_at and next_review_at <= now)

    if status == 'new':
        primary_label = 'Изучать'
        primary_kind = 'set_learning'
        secondary_label = None
        extra_study = False
    elif status == 'learning':
        primary_label = 'Продолжить изучение'
        primary_kind = 'study'
        secondary_label = None
        extra_study = True
    elif status == 'review' and is_due_now:
        primary_label = 'Повторить сейчас'
        primary_kind = 'study'
        secondary_label = None
        extra_study = False
    elif status == 'review':
        primary_label = f'Повторение {_format_review_time(next_review_at, now)}'
        primary_kind = 'disabled'
        secondary_label = 'Повторить досрочно'
        extra_study = False
    else:
        primary_label = 'Повторить'
        primary_kind = 'study'
        secondary_label = None
        extra_study = True

    direction_rows = []
    for direction in directions:
        correct = direction.correct_count or 0
        incorrect = direction.incorrect_count or 0
        direction_rows.append({
            'label': _DIRECTION_LABELS.get(direction.direction, direction.direction or 'Направление'),
            'state_label': _STATE_LABELS.get(direction.state or 'new', direction.state or 'Новая'),
            'next_review_label': _format_review_time(direction.next_review, now),
            'accuracy_label': f'{_direction_accuracy(correct, incorrect)}%',
            'answers_label': f'{correct} / {incorrect}',
            'interval_label': f'{direction.interval or 0} дн.',
            'lapses': direction.lapses or 0,
        })

    return {
        'status': status,
        'status_css': 'mastered' if status == 'mastered' else status,
        'status_label': status_labels.get(status, status),
        'status_description': descriptions.get(status, ''),
        'badge_label': badge_labels.get(status, status),
        'primary_action_label': primary_label,
        'primary_action_kind': primary_kind,
        'primary_action_extra_study': extra_study,
        'secondary_action_label': secondary_label,
        'next_review_label': _format_review_time(next_review_at, now),
        'accuracy_label': f'{user_word.performance_percentage}%',
        'correct_total': correct_total,
        'incorrect_total': incorrect_total,
        'repetitions_total': repetitions_total,
        'lapses_total': lapses_total,
        'interval_label': interval_label,
        'has_directions': bool(directions),
        'directions': direction_rows,
    }


def _candidate_base_query(public_only: bool = False):
    query = CollectionWords.query.options(
        selectinload(CollectionWords.topics),
        selectinload(CollectionWords.collections),
        selectinload(CollectionWords.base_word),
        selectinload(CollectionWords.phrasal_verbs),
    )
    if public_only:
        from app.curriculum.routes.public import PUBLIC_CEFR_CODES

        query = query.filter(CollectionWords.level.in_(PUBLIC_CEFR_CODES))
    return query


def _rank_key(word: CollectionWords):
    return (word.frequency_rank if word.frequency_rank and word.frequency_rank > 0 else 999999, word.english_word or '')


def _contextual_translation(value: str | None) -> str:
    text = _clean_optional_text(value)
    if not text:
        return ''
    for separator in (',', ';', '/'):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
            break
    return text


def _choose_related_reason(reasons: list[str]) -> str:
    unique = list(dict.fromkeys(reasons))
    priority = [
        'синоним',
        'антоним',
        'базовое слово',
        'фразовый вариант',
        'люди и роли',
        'учеба',
        'приветствия',
        'та же тема',
        'та же подборка',
        'та же глагольная семья',
    ]
    for label in priority:
        if label in unique:
            return label
    return unique[0] if unique else 'близко по уровню и частотности'


def _score_related_word(
    source: CollectionWords,
    candidate: CollectionWords,
    source_topic_ids: set[int],
    source_collection_ids: set[int],
    source_synonyms: set[str],
    source_antonyms: set[str],
) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    candidate_lookup = _normalise_lookup(candidate.english_word)
    candidate_synonyms = {_normalise_lookup(item) for item in normalise_word_list(candidate.synonyms)}
    candidate_antonyms = {_normalise_lookup(item) for item in normalise_word_list(candidate.antonyms)}
    source_lookup = _normalise_lookup(source.english_word)
    source_groups = _semantic_group_labels(source_lookup)
    candidate_groups = _semantic_group_labels(candidate_lookup)

    if candidate.id == source.base_word_id:
        score += 90
        reasons.append('базовое слово')
    if candidate.base_word_id == source.id:
        score += 85
        reasons.append('фразовый вариант')
    if source.base_word_id and candidate.base_word_id == source.base_word_id:
        score += 70
        reasons.append('та же глагольная семья')

    if candidate_lookup in source_synonyms or source_lookup in candidate_synonyms:
        score += 80
        reasons.append('синоним')
    if candidate_lookup in source_antonyms or source_lookup in candidate_antonyms:
        score += 65
        reasons.append('антоним')

    shared_synonyms = source_synonyms.intersection(candidate_synonyms)
    if shared_synonyms:
        score += 35 + min(len(shared_synonyms), 3) * 5
        reasons.append('общие синонимы')

    candidate_topic_ids = {topic.id for topic in getattr(candidate, 'topics', [])}
    shared_topics = source_topic_ids.intersection(candidate_topic_ids)
    if shared_topics:
        score += 45 + min(len(shared_topics), 3) * 7
        reasons.append('та же тема')

    candidate_collection_ids = {collection.id for collection in getattr(candidate, 'collections', [])}
    shared_collections = source_collection_ids.intersection(candidate_collection_ids)
    if shared_collections:
        score += 35 + min(len(shared_collections), 3) * 5
        reasons.append('та же подборка')

    shared_groups = source_groups.intersection(candidate_groups)
    if shared_groups:
        score += 42
        reasons.append(sorted(shared_groups)[0])

    if source.level and candidate.level == source.level:
        score += 18
        reasons.append(f'уровень {source.level}')
    if source.frequency_band and candidate.frequency_band == source.frequency_band:
        score += 12
        if not reasons:
            reasons.append(frequency_band_label(source.frequency_band))

    if source.frequency_rank and candidate.frequency_rank:
        rank_gap = abs(source.frequency_rank - candidate.frequency_rank)
        if rank_gap <= 250:
            score += 14
        elif rank_gap <= 1000:
            score += 8
        elif rank_gap <= 3000:
            score += 4

    source_tokens = set(source_lookup.replace('-', ' ').split())
    candidate_tokens = set(candidate_lookup.replace('-', ' ').split())
    if source_tokens and candidate_tokens and source_tokens.intersection(candidate_tokens):
        score += 18
        reasons.append('похожая форма')
    elif source_lookup[:4] and source_lookup[:4] == candidate_lookup[:4]:
        score += 10
        reasons.append('похожее написание')

    if candidate.item_type == source.item_type:
        score += 4

    source_is_phrase = ' ' in source_lookup
    candidate_is_phrase = ' ' in candidate_lookup
    if source_is_phrase != candidate_is_phrase and not (
        candidate.id == source.base_word_id
        or candidate.base_word_id == source.id
        or candidate_lookup in source_synonyms
        or source_lookup in candidate_synonyms
    ):
        score -= 32

    reason = _choose_related_reason(reasons)
    return score, reason


def get_related_words(word: CollectionWords, *, limit: int = 6, public_only: bool = False) -> list[CollectionWords]:
    """Return deterministic, explainable related words instead of random same-level picks."""
    source_synonyms = {_normalise_lookup(item) for item in normalise_word_list(word.synonyms)}
    source_antonyms = {_normalise_lookup(item) for item in normalise_word_list(word.antonyms)}
    source_terms = {term for term in source_synonyms.union(source_antonyms) if term}
    source_topic_ids = {topic.id for topic in getattr(word, 'topics', [])}
    source_collection_ids = {collection.id for collection in getattr(word, 'collections', [])}

    candidates: dict[int, CollectionWords] = {}

    def add_results(query, cap: int = 80) -> None:
        for item in query.limit(cap).all():
            if item.id != word.id:
                candidates[item.id] = item

    if source_terms:
        add_results(
            _candidate_base_query(public_only)
            .filter(func.lower(CollectionWords.english_word).in_(source_terms))
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=40,
        )

    family_ids = {word.base_word_id} if word.base_word_id else set()
    family_ids.update(item.id for item in getattr(word, 'phrasal_verbs', []) or [])
    if family_ids:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.id.in_([item_id for item_id in family_ids if item_id]))
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=40,
        )

    if word.base_word_id:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.base_word_id == word.base_word_id)
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=40,
        )
    else:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.base_word_id == word.id)
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=40,
        )

    if source_topic_ids:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.topics.any(Topic.id.in_(source_topic_ids)))
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=120,
        )

    if source_collection_ids:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.collections.any(Collection.id.in_(source_collection_ids)))
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=120,
        )

    fallback_filters = []
    if word.level:
        fallback_filters.append(CollectionWords.level == word.level)
    if word.frequency_band:
        fallback_filters.append(CollectionWords.frequency_band == word.frequency_band)
    if fallback_filters:
        add_results(
            _candidate_base_query(public_only)
            .filter(CollectionWords.id != word.id)
            .filter(or_(*fallback_filters))
            .order_by(CollectionWords.frequency_rank.asc().nullslast(), CollectionWords.english_word.asc()),
            cap=160,
        )

    scored = []
    for candidate in candidates.values():
        score, reason = _score_related_word(
            word,
            candidate,
            source_topic_ids,
            source_collection_ids,
            source_synonyms,
            source_antonyms,
        )
        if score > 0:
            candidate.related_reason = reason
            candidate.related_translation = _contextual_translation(candidate.russian_word)
            scored.append((score, _rank_key(candidate), candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    strong = [candidate for score, _, candidate in scored if score >= 45]
    return strong[:limit]
