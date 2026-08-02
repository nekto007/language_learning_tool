from app.daily_plan.items.phrase_review import _candidate, _is_usable_phrase


def test_phrase_review_accepts_short_a1_a2_sentence():
    assert _is_usable_phrase('I can swim very well.')


def test_phrase_review_rejects_single_word_answer():
    assert not _is_usable_phrase('swim')


def test_phrase_review_keeps_only_distinct_usable_alternatives():
    item = _candidate(
        identifier='recent:1:0',
        prompt='Я умею плавать.',
        answer='I can swim.',
        alternatives=['I can swim', 'I can swim very well.', 'swim'],
        source='recent_module',
    )

    assert item is not None
    assert item['accepted_answers'] == ['I can swim.', 'I can swim very well.']
