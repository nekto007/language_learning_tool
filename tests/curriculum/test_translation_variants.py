"""Reviewed translations are a finite allowlist, not similarity grading.

These tests are independent of PostgreSQL and the private JSON curriculum.
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'translation_variants', Path(__file__).resolve().parents[2] /
    'app/curriculum/translation_variants.py')
_VARIANTS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VARIANTS)
get_translation_variants = _VARIANTS.get_translation_variants
translation_reference = _VARIANTS.translation_reference

MEDIA_ENGLISH = 'The investigative team spent six months verifying the anonymous documents.'
MEDIA_RUSSIAN = 'Расследовательская команда потратила полгода на проверку анонимных документов.'


def test_half_year_and_checking_are_explicitly_supported_together():
    variants = get_translation_variants(MEDIA_ENGLISH, MEDIA_RUSSIAN)
    assert 'The investigative team spent half a year checking the anonymous documents.' in variants
    assert 'The investigative team spent half a year verifying the anonymous documents.' in variants
    assert 'The investigative team spent six months checking the anonymous documents.' in variants
    assert len(variants) == len(set(variants))
    assert MEDIA_ENGLISH not in variants


@pytest.mark.parametrize('incorrect', [
    'The investigative team spent a year checking the anonymous documents.',
    'The investigative team spent five months checking the anonymous documents.',
    'The investigative team did not spend half a year checking the anonymous documents.',
    'The investigative team will spend half a year checking the anonymous documents.',
    'The anonymous documents spent half a year checking the investigative team.',
    'The investigative team spent half a year checking the public documents.',
])
def test_similar_but_wrong_translations_are_never_generated(incorrect):
    assert incorrect not in get_translation_variants(MEDIA_ENGLISH, MEDIA_RUSSIAN)


def test_rules_are_bound_to_complete_bilingual_source_not_a_word_or_topic():
    assert get_translation_variants(MEDIA_ENGLISH, 'Команда не проверяла эти документы.') == ()
    assert get_translation_variants(
        'The investigative team spent seven months verifying the anonymous documents.', MEDIA_RUSSIAN) == ()
    assert get_translation_variants('I bought a house.', 'Я купил дом.') == ()
    assert get_translation_variants('We eat a lot of apples.', 'Мы едим много яблок.') == ()


def test_small_case_and_article_are_authored_correctly():
    assert get_translation_variants(
        'A tailored suit fits far better than an off-the-rack one.',
        'Костюм, сшитый на заказ, сидит гораздо лучше готового.') == (
            'A tailored suit fits far better than a ready-to-wear one.',)
    assert 'At night, children sleep.' in get_translation_variants(
        'Children sleep at night.', 'Дети спят ночью.')


def test_moving_a_future_time_frame_does_not_change_promise_time():
    variants = get_translation_variants(
        'The landlord promised to fix the roof next week.',
        'Арендодатель обещал починить крышу на следующей неделе.')
    assert 'The landlord promised to repair the roof next week.' in variants
    assert not any(answer.startswith('Next week,') for answer in variants)
    assert not any('appointment for.' in answer for answer in get_translation_variants(
        'I have a dental appointment for tomorrow.', 'У меня запись к стоматологу на завтра.'))


def test_conditional_reordering_retains_negation_and_tenses():
    variants = get_translation_variants(
        "If I weren't afraid of failure, I would have pursued this dream long ago.",
        'Если бы я не боялся неудачи, я бы давно осуществил эту мечту.')
    assert variants == ("I would have pursued this dream long ago if I weren't afraid of failure.",)


@pytest.mark.parametrize(('english', 'russian', 'expected'), [
    ('I have a big family.', 'У меня большая семья.', 'I have a large family.'),
    ('A clever fox caught a mouse.', 'Хитрая лиса поймала мышь.', 'A cunning fox caught a mouse.'),
    ('This algorithm looks for patterns in huge sets of data.',
     'Этот алгоритм ищет закономерности в огромных массивах данных.',
     'This algorithm searches for patterns in huge sets of data.'),
    ('Please close the door.', 'Закрой дверь, пожалуйста.', 'Close the door, please.'),
])
def test_finite_equivalents_cover_different_levels(english, russian, expected):
    assert expected in get_translation_variants(english, russian)


def test_ambulance_reference_does_not_confuse_after_with_within():
    legacy = ('The ambulance arrived within five minutes.', 'Скорая приехала через пять минут.')
    expected = ('The ambulance arrived after five minutes.', legacy[1])
    assert translation_reference(*legacy) == expected
    assert translation_reference(*expected) == expected
    assert translation_reference(legacy[0], 'Скорая приехала не позднее чем через пять минут.') == (
        legacy[0], 'Скорая приехала не позднее чем через пять минут.')


def test_hanging_state_is_not_omitted_from_towel_reference():
    assert translation_reference('The towel is in the bathroom.', 'Полотенце висит в ванной.') == (
        'The towel is hanging in the bathroom.', 'Полотенце висит в ванной.')


def test_break_even_is_not_profit_and_keeps_the_target_idiom():
    english = 'Despite record revenue, the company barely broke even.'
    old_russian = 'Несмотря на рекордную выручку, компания едва вышла на прибыль.'
    reference = translation_reference(english, old_russian)
    assert reference == (english, 'Несмотря на рекордную выручку, компания едва достигла безубыточности.')
    assert get_translation_variants(english, old_russian) == get_translation_variants(*reference)
    assert 'The company barely broke even despite record revenue.' in get_translation_variants(*reference)


def test_unknown_source_does_not_get_an_automatic_pass_or_mutation():
    source = ('This is a blue book.', 'Это синяя книга.')
    assert translation_reference(*source) == source
    assert get_translation_variants(*source) == ()
    assert get_translation_variants('', '') == ()
