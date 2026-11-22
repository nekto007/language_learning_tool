"""Artificial protocol fixtures; no private learning texts or questions."""

import json


def write_pack(path):
    items = []
    for index in range(1, 16):
        questions = [{
            'id': f'q{number}',
            'instruction': 'Select a fixture option.',
            'prompt': f'Fixture question {number}?',
            'prompt_translation': 'Test prompt translation.',
            'options': [{'id': key, 'text': f'Fixture option {key}.'} for key in ('a', 'b', 'c')],
            'correct_option': 'b',
            'explanation': 'Synthetic explanation: «Fixture».',
        } for number in range(1, 3 if index <= 2 else 4)]
        items.append({
            'slug': f'llt-a1-reading-{index:02}',
            'title': f'Fixture {index:02}',
            'text': ' '.join(['Fixture'] * (44 + (index - 1) * 9)) + '.',
            'reading': {
                'version': 1, 'format': ('short_text', 'dialogue', 'story')[(index - 1) % 3],
                'stage': ('start' if index <= 5 else 'growing' if index <= 10 else 'confident'),
                'order': index, 'estimated_minutes': 2, 'after_topics': [], 'focus': 'Fixture metadata.',
                'glossary': [{'english': f'fixture {n}', 'translation': f'placeholder {n}'} for n in range(3)],
                'questions': questions,
            },
        })
    path.write_text(json.dumps({'version': 1, 'author': 'Test fixture', 'items': items}), encoding='utf-8')
    return path
