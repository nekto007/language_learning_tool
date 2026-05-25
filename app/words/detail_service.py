"""Presentation helpers for word detail pages."""

from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.words.models import Collection, CollectionWords, Topic


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
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _normalise_lookup(value: str) -> str:
    return (value or '').strip().lower()


def frequency_band_label(band) -> str:
    labels = {
        1: 'Top 1000',
        2: 'Top 3000',
        3: 'Top 10000',
    }
    return labels.get(band, 'Не указана')


def item_type_label(item_type: str | None) -> str:
    labels = {
        'word': 'Слово',
        'phrasal_verb': 'Фразовый глагол',
    }
    return labels.get(item_type or 'word', item_type or 'Слово')


def build_word_profile(word: CollectionWords) -> dict:
    """Prepare all user-facing collection_words fields for word detail pages."""
    synonyms = normalise_word_list(word.synonyms)
    antonyms = normalise_word_list(word.antonyms)
    phrasal_verbs = sorted(
        list(getattr(word, 'phrasal_verbs', []) or []),
        key=lambda item: ((item.frequency_rank or 999999), item.english_word or ''),
    )
    audio_available = bool(word.get_download and word.listening)

    facts = [
        {'label': 'ID', 'value': word.id},
        {'label': 'Тип', 'value': item_type_label(word.item_type)},
        {'label': 'Уровень', 'value': word.level or 'Не указан'},
        {
            'label': 'Частотность',
            'value': f'#{word.frequency_rank}' if word.frequency_rank else 'Не указана',
        },
        {'label': 'Частотная группа', 'value': frequency_band_label(word.frequency_band)},
        {'label': 'Brown corpus', 'value': 'Да' if word.brown else 'Нет'},
        {'label': 'Аудио', 'value': 'Есть' if audio_available else 'Нет'},
    ]

    return {
        'synonyms': synonyms,
        'antonyms': antonyms,
        'frequency_band_label': frequency_band_label(word.frequency_band),
        'item_type_label': item_type_label(word.item_type),
        'audio_available': audio_available,
        'facts': facts,
        'base_word': word.base_word,
        'phrasal_verbs': phrasal_verbs[:8],
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

    reason = ', '.join(dict.fromkeys(reasons[:2])) or 'близко по уровню и частотности'
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
            scored.append((score, _rank_key(candidate), candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [candidate for _, _, candidate in scored[:limit]]
