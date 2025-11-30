# app/curriculum/services/comprehension_generator.py
"""
Comprehension MCQ and Cloze Practice Generator

Generates comprehension questions and cloze exercises from text.
Used for comprehension_mcq and cloze_practice lesson types.
"""

import re
import random
from typing import Dict, List, Any, Optional


class ComprehensionMCQGenerator:
    """
    Generates multiple choice comprehension questions from text.

    Uses text analysis to create questions about:
    - Main idea / topic
    - Specific details mentioned
    - Vocabulary in context
    - Inference questions
    """

    # Question templates for different question types
    QUESTION_TEMPLATES = {
        'main_idea': [
            'What is the main topic of this passage?',
            'What is the passage primarily about?',
            'Which statement best summarizes the passage?',
        ],
        'detail': [
            'According to the passage, what happens?',
            'Based on the text, which statement is true?',
            'What does the passage mention about the events?',
        ],
        'vocabulary': [
            'In context, what does the word "{word}" most likely mean?',
            'The word "{word}" in the passage is closest in meaning to:',
        ],
        'inference': [
            'What can we infer from the passage?',
            'Based on the passage, what is most likely true?',
            'The author implies that:',
        ],
        'purpose': [
            'What is the purpose of this passage?',
            'Why did the author write this passage?',
        ],
    }

    @classmethod
    def generate_questions(cls, text: str, num_questions: int = 10) -> Dict[str, Any]:
        """
        Generate comprehension questions from text.

        Args:
            text: The passage text to generate questions from
            num_questions: Number of questions to generate (default 10)

        Returns:
            Dict with 'questions' list containing question objects
        """
        if not text or len(text) < 50:
            return cls._get_fallback_questions()

        questions = []
        sentences = cls._split_into_sentences(text)
        words = cls._extract_key_words(text)

        # Generate different types of questions
        questions.append(cls._generate_main_idea_question(text, sentences))

        # Add detail questions (3-4)
        for i in range(min(4, len(sentences) // 2)):
            q = cls._generate_detail_question(sentences, i)
            if q:
                questions.append(q)

        # Add vocabulary questions (2-3)
        for word in words[:3]:
            q = cls._generate_vocabulary_question(word, text)
            if q:
                questions.append(q)

        # Add inference questions (2)
        for i in range(2):
            questions.append(cls._generate_inference_question(text, sentences))

        # Shuffle and limit
        random.shuffle(questions)
        questions = questions[:num_questions]

        # Ensure we have enough questions
        while len(questions) < num_questions:
            questions.append(cls._generate_generic_question(len(questions) + 1))

        return {'questions': questions}

    @classmethod
    def _split_into_sentences(cls, text: str) -> List[str]:
        """Split text into sentences."""
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]

    @classmethod
    def _extract_key_words(cls, text: str) -> List[str]:
        """Extract key words from text (longer, less common words)."""
        words = re.findall(r'\b[a-zA-Z]{6,}\b', text)
        # Get unique words, prefer longer ones
        unique_words = list(set(words))
        unique_words.sort(key=len, reverse=True)
        return unique_words[:10]

    @classmethod
    def _generate_main_idea_question(cls, text: str, sentences: List[str]) -> Dict:
        """Generate a main idea question."""
        template = random.choice(cls.QUESTION_TEMPLATES['main_idea'])

        # First sentence often contains the main idea
        correct_option = sentences[0][:80] + "..." if len(sentences[0]) > 80 else sentences[0]

        # Generate distractors from other parts
        distractors = []
        if len(sentences) > 2:
            distractors.append("A minor detail about " + sentences[-1][:30])
        distractors.extend([
            "An unrelated topic not mentioned in the text",
            "The opposite of what the passage describes",
        ])

        options = [correct_option] + distractors[:3]
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'This captures the main idea presented in the passage.'
        }

    @classmethod
    def _generate_detail_question(cls, sentences: List[str], index: int) -> Optional[Dict]:
        """Generate a detail question about specific sentence."""
        if index >= len(sentences):
            return None

        sentence = sentences[index]
        template = random.choice(cls.QUESTION_TEMPLATES['detail'])

        correct_option = sentence[:80] + "..." if len(sentence) > 80 else sentence

        distractors = [
            "This detail is not mentioned in the passage",
            "The opposite is stated in the text",
            "This is a different event from the story",
        ]

        options = [correct_option] + distractors[:3]
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': f'This detail is mentioned in the passage.'
        }

    @classmethod
    def _generate_vocabulary_question(cls, word: str, text: str) -> Optional[Dict]:
        """Generate a vocabulary in context question."""
        template = random.choice(cls.QUESTION_TEMPLATES['vocabulary']).format(word=word)

        # Simple synonyms/definitions (placeholder - would need dictionary in production)
        correct_option = f"A word related to '{word}'"

        distractors = [
            "The opposite meaning",
            "An unrelated word",
            "A word that sounds similar but means different",
        ]

        options = [correct_option] + distractors
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': f'In this context, "{word}" relates to the meaning described.'
        }

    @classmethod
    def _generate_inference_question(cls, text: str, sentences: List[str]) -> Dict:
        """Generate an inference question."""
        template = random.choice(cls.QUESTION_TEMPLATES['inference'])

        # Create inference based on text content
        correct_option = "Based on the events described, we can conclude..."

        distractors = [
            "The text contradicts this interpretation",
            "There is no evidence for this in the passage",
            "This goes against what the author implies",
        ]

        options = [correct_option] + distractors
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'This inference is supported by the passage content.'
        }

    @classmethod
    def _generate_generic_question(cls, num: int) -> Dict:
        """Generate a generic question as fallback."""
        return {
            'question': f'Question {num}: What does the passage suggest?',
            'options': [
                'The main point of the passage',
                'A secondary detail',
                'An unmentioned topic',
                'The opposite of the main idea'
            ],
            'correct': 0,
            'explanation': 'This relates to the content of the passage.'
        }

    @classmethod
    def _get_fallback_questions(cls) -> Dict[str, Any]:
        """Return fallback questions if text is too short."""
        return {
            'questions': [
                {
                    'question': 'What is the main topic of the passage?',
                    'options': ['The main theme', 'A minor detail', 'Unrelated topic', 'Opposite meaning'],
                    'correct': 0,
                    'explanation': 'This question tests understanding of the main idea.'
                }
            ] * 10
        }


class ClozePracticeGenerator:
    """
    Generates cloze (fill-in-the-blank) exercises from text.

    Removes key words and creates gaps for students to fill.
    """

    # Words to target for removal (function words, common verbs, prepositions)
    TARGET_PATTERNS = [
        r'\b(have|has|had)\b',
        r'\b(is|are|was|were|been|being)\b',
        r'\b(will|would|could|should|might|must|can|may)\b',
        r'\b(the|a|an)\b',
        r'\b(in|on|at|by|for|with|to|from|of)\b',
        r'\b(and|but|or|so|because|although|however)\b',
        r'\b(very|quite|really|just|only|even|also)\b',
        r'\b(this|that|these|those)\b',
        r'\b(who|which|what|where|when|how|why)\b',
    ]

    @classmethod
    def generate_cloze(cls, text: str, num_gaps: int = 8) -> Dict[str, Any]:
        """
        Generate a cloze exercise from text.

        Args:
            text: The passage text to create gaps in
            num_gaps: Number of gaps to create (default 8)

        Returns:
            Dict with 'text' (with gap placeholders) and 'gaps' list
        """
        if not text or len(text) < 100:
            return cls._get_fallback_cloze()

        # Find all potential words to remove
        candidates = []

        for pattern in cls.TARGET_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidates.append({
                    'word': match.group(),
                    'start': match.start(),
                    'end': match.end(),
                    'hint': cls._get_hint_for_word(match.group())
                })

        # Remove duplicates (same position)
        seen_positions = set()
        unique_candidates = []
        for c in candidates:
            if c['start'] not in seen_positions:
                seen_positions.add(c['start'])
                unique_candidates.append(c)

        # Sort by position and select evenly distributed gaps
        unique_candidates.sort(key=lambda x: x['start'])

        if len(unique_candidates) < num_gaps:
            num_gaps = len(unique_candidates)

        # Select gaps evenly distributed through text
        if num_gaps > 0:
            step = len(unique_candidates) // num_gaps
            selected = [unique_candidates[i * step] for i in range(num_gaps)]
        else:
            selected = []

        # Sort selected by position (ascending for gap numbering)
        selected.sort(key=lambda x: x['start'])

        # Assign gap numbers (1, 2, 3...)
        for i, gap in enumerate(selected):
            gap['gap_num'] = i + 1

        # Sort by position in reverse for replacement (to preserve positions)
        selected.sort(key=lambda x: x['start'], reverse=True)

        # Create cloze text and gaps list
        cloze_text = text
        gaps = []

        for gap in selected:
            placeholder = f"({gap['gap_num']}) ______"
            cloze_text = cloze_text[:gap['start']] + placeholder + cloze_text[gap['end']:]

            gaps.append({
                'id': gap['gap_num'],
                'answer': gap['word'].lower(),
                'hint': gap['hint']
            })

        # Sort gaps by id
        gaps.sort(key=lambda x: x['id'])

        return {
            'text': cloze_text,
            'gaps': gaps
        }

    @classmethod
    def _get_hint_for_word(cls, word: str) -> str:
        """Get a grammatical hint for the word."""
        word_lower = word.lower()

        if word_lower in ['have', 'has', 'had']:
            return 'auxiliary verb (have)'
        elif word_lower in ['is', 'are', 'was', 'were', 'been', 'being']:
            return 'verb to be'
        elif word_lower in ['will', 'would', 'could', 'should', 'might', 'must', 'can', 'may']:
            return 'modal verb'
        elif word_lower in ['the', 'a', 'an']:
            return 'article'
        elif word_lower in ['in', 'on', 'at', 'by', 'for', 'with', 'to', 'from', 'of']:
            return 'preposition'
        elif word_lower in ['and', 'but', 'or', 'so', 'because', 'although', 'however']:
            return 'conjunction'
        elif word_lower in ['very', 'quite', 'really', 'just', 'only', 'even', 'also']:
            return 'adverb'
        elif word_lower in ['this', 'that', 'these', 'those']:
            return 'demonstrative'
        elif word_lower in ['who', 'which', 'what', 'where', 'when', 'how', 'why']:
            return 'question word'
        else:
            return 'word'

    @classmethod
    def _get_fallback_cloze(cls) -> Dict[str, Any]:
        """Return fallback cloze if text is too short."""
        return {
            'text': """The importance of reading cannot (1) ______ overstated. When we read, we not only gain knowledge (2) ______ also improve our vocabulary. Many successful people attribute their achievements (3) ______ the habit of reading regularly.

Reading fiction, (4) ______ particular, helps us develop empathy by allowing us to see the world through different perspectives. It has (5) ______ shown that regular readers are more likely to understand others.

Furthermore, reading is one of the (6) ______ effective ways to reduce stress. Studies have found that just six minutes of reading can reduce stress levels (7) ______ up to 68 percent. This makes it even more beneficial (8) ______ watching television.""",
            'gaps': [
                {'id': 1, 'answer': 'be', 'hint': 'auxiliary verb'},
                {'id': 2, 'answer': 'but', 'hint': 'conjunction'},
                {'id': 3, 'answer': 'to', 'hint': 'preposition'},
                {'id': 4, 'answer': 'in', 'hint': 'preposition (phrase)'},
                {'id': 5, 'answer': 'been', 'hint': 'past participle'},
                {'id': 6, 'answer': 'most', 'hint': 'superlative'},
                {'id': 7, 'answer': 'by', 'hint': 'preposition'},
                {'id': 8, 'answer': 'than', 'hint': 'comparison word'}
            ]
        }
