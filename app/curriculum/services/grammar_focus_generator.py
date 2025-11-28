# app/curriculum/services/grammar_focus_generator.py
"""
Grammar Focus Generator v1.0

Generates grammar lesson content from pre-built templates in JSON module files.
Maps grammar topics to their explanations, examples, and exercises.

Used by DailySliceGenerator for grammar_focus lessons.
"""

import json
import logging
import os
import glob
import random
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Base path for module JSON files
MODULE_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    ''
)


class GrammarFocusGenerator:
    """
    Generates grammar lesson content from JSON module files.

    Each grammar topic has:
    - title: Grammar topic name
    - introduction: Brief intro text
    - sections: [{subtitle, description, table: [{...examples}]}]
    - important_notes: List of key points
    - exercises: Quiz questions for practice
    """

    _grammar_library: Dict[str, List[Dict]] = {}
    _loaded = False

    @classmethod
    def load_grammar_library(cls) -> None:
        """Load all grammar content from JSON module files."""
        if cls._loaded:
            return

        cls._grammar_library = {
            'A1': [],
            'A2': [],
            'B1': [],
            'B2': [],
            'C1': [],
            'C2': []
        }

        pattern = os.path.join(MODULE_JSON_PATH, 'module_*.json')
        json_files = glob.glob(pattern)

        logger.info(f"Loading grammar from {len(json_files)} module files")

        for filepath in json_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                module_level = data.get('module', {}).get('level', 'B1')

                for lesson in data.get('module', {}).get('lessons', []):
                    if lesson.get('type') == 'grammar':
                        grammar_content = lesson.get('content', {}).get('grammar_explanation', {})

                        if grammar_content.get('sections'):
                            grammar_entry = {
                                'grammar_focus': lesson.get('grammar_focus', ''),
                                'title': grammar_content.get('title', ''),
                                'introduction': grammar_content.get('introduction', ''),
                                'sections': grammar_content.get('sections', []),
                                'important_notes': grammar_content.get('important_notes', []),
                                'source_file': os.path.basename(filepath)
                            }

                            if module_level in cls._grammar_library:
                                cls._grammar_library[module_level].append(grammar_entry)
                            else:
                                cls._grammar_library['B1'].append(grammar_entry)

            except Exception as e:
                logger.warning(f"Error loading grammar from {filepath}: {e}")
                continue

        total = sum(len(v) for v in cls._grammar_library.values())
        logger.info(f"Loaded {total} grammar topics: " +
                   ", ".join(f"{k}={len(v)}" for k, v in cls._grammar_library.items()))

        cls._loaded = True

    @classmethod
    def get_grammar_content(cls, level: str = 'B1', topic_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Get grammar content for a specific level.

        Args:
            level: CEFR level (A1, A2, B1, B2, C1, C2)
            topic_index: Optional index to select specific topic (cycles through available)

        Returns:
            Grammar content dict with title, sections, exercises, etc.
        """
        cls.load_grammar_library()

        level_topics = cls._grammar_library.get(level, [])

        # If no topics for this level, try adjacent levels
        if not level_topics:
            for fallback_level in ['B1', 'A2', 'B2', 'A1']:
                level_topics = cls._grammar_library.get(fallback_level, [])
                if level_topics:
                    break

        if not level_topics:
            logger.warning(f"No grammar topics found for level {level}")
            return cls._get_fallback_grammar()

        # Select topic by index (cycles through available topics)
        if topic_index is not None:
            idx = topic_index % len(level_topics)
        else:
            idx = random.randint(0, len(level_topics) - 1)

        grammar = level_topics[idx]

        # Generate exercises based on sections
        exercises = cls._generate_exercises(grammar)

        return {
            'title': grammar['title'],
            'introduction': grammar['introduction'],
            'sections': grammar['sections'],
            'important_notes': grammar['important_notes'],
            'exercises': exercises,
            'estimated_time': 15,
            'pass_score': 70
        }

    @classmethod
    def get_grammar_for_day(cls, level: str, day_number: int) -> Dict[str, Any]:
        """
        Get grammar content for a specific day number.
        Uses day_number to cycle through topics deterministically.

        Args:
            level: CEFR level
            day_number: Day number in the course (used for topic selection)

        Returns:
            Grammar content dict
        """
        # Map day_number to grammar topic index
        # Grammar appears on days 2, 8, 14, 20, etc. (every 6th day starting from 2)
        grammar_lesson_number = (day_number - 2) // 6

        return cls.get_grammar_content(level, topic_index=grammar_lesson_number)

    @classmethod
    def _generate_exercises(cls, grammar: Dict) -> List[Dict]:
        """
        Generate quiz exercises from grammar sections.

        Creates multiple-choice questions based on the examples in sections.
        """
        exercises = []

        for section in grammar.get('sections', []):
            table = section.get('table', [])

            if len(table) >= 2:
                # Create a question from the first example
                correct_example = table[0]

                # Get the example sentence
                example_sentence = correct_example.get('example', '')
                translation = correct_example.get('translation', '')

                if example_sentence:
                    # Create fill-in-the-blank style question
                    verb = correct_example.get('verb', '')

                    if verb:
                        # Create question about verb form
                        exercises.append({
                            'question': f'Какая форма правильная в предложении: "{example_sentence}"?',
                            'options': [
                                verb,  # Correct
                                verb.replace('have', 'has') if 'have' in verb else verb + 's',
                                verb.replace('has', 'have') if 'has' in verb else verb[:-1] if verb.endswith('s') else verb,
                                'was ' + verb.split()[-1] if len(verb.split()) > 1 else 'was ' + verb
                            ],
                            'correct': 0,
                            'explanation': translation or section.get('description', '')
                        })

        # Add general comprehension questions
        title = grammar.get('title', '')
        notes = grammar.get('important_notes', [])

        if notes:
            exercises.append({
                'question': f'Какое утверждение верно для "{title}"?',
                'options': [
                    notes[0].replace('⚠️ ', '') if notes else 'Это правило',
                    'Используется только в прошедшем времени',
                    'Требует вспомогательного глагола do',
                    'Не имеет исключений'
                ],
                'correct': 0,
                'explanation': notes[0] if notes else ''
            })

        # Ensure at least 4 exercises
        while len(exercises) < 4:
            exercises.append({
                'question': f'Вопрос о "{title}" #{len(exercises) + 1}',
                'options': ['Вариант A', 'Вариант B', 'Вариант C', 'Вариант D'],
                'correct': 0,
                'explanation': grammar.get('introduction', '')[:100]
            })

        return exercises[:5]  # Return up to 5 exercises

    @classmethod
    def _get_fallback_grammar(cls) -> Dict[str, Any]:
        """Return fallback grammar content if no topics found."""
        return {
            'title': 'Present Perfect Tense',
            'introduction': 'The Present Perfect is used to describe actions with relevance to the present.',
            'sections': [
                {
                    'subtitle': 'Formation',
                    'description': 'have/has + past participle (V3)',
                    'table': [
                        {
                            'pronoun': 'I/You/We/They',
                            'verb': 'have done',
                            'example': 'I have visited Paris',
                            'translation': 'Я посещал Париж'
                        },
                        {
                            'pronoun': 'He/She/It',
                            'verb': 'has done',
                            'example': 'She has visited Paris',
                            'translation': 'Она посещала Париж'
                        }
                    ]
                }
            ],
            'important_notes': [
                'Used for experiences without specific time',
                'Used with for/since for duration',
                'Used for recent actions with present result'
            ],
            'exercises': [
                {
                    'question': 'Which sentence is correct?',
                    'options': [
                        'I have seen him before.',
                        'I have seen him yesterday.',
                        'I have saw him before.',
                        'I seen him before.'
                    ],
                    'correct': 0,
                    'explanation': 'Present Perfect is used for experiences without specific time.'
                }
            ],
            'estimated_time': 15,
            'pass_score': 70
        }

    @classmethod
    def get_available_topics(cls, level: str = None) -> List[Dict[str, str]]:
        """
        Get list of available grammar topics.

        Args:
            level: Optional CEFR level filter

        Returns:
            List of {title, grammar_focus, level} dicts
        """
        cls.load_grammar_library()

        topics = []
        levels_to_check = [level] if level else cls._grammar_library.keys()

        for lvl in levels_to_check:
            for grammar in cls._grammar_library.get(lvl, []):
                topics.append({
                    'title': grammar['title'],
                    'grammar_focus': grammar['grammar_focus'],
                    'level': lvl
                })

        return topics
