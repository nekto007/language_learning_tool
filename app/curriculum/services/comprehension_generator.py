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

    # Question templates for different question types (Russian)
    QUESTION_TEMPLATES = {
        'main_idea': [
            'О чём этот текст?',
            'Какова главная тема отрывка?',
            'Какое утверждение лучше всего описывает текст?',
        ],
        'detail': [
            'Согласно тексту, что происходит?',
            'Какое утверждение соответствует тексту?',
            'Что упоминается в тексте?',
        ],
        'vocabulary': [
            'Что означает слово "{word}" в данном контексте?',
            'Какое значение имеет слово "{word}" в тексте?',
        ],
        'inference': [
            'Что можно понять из текста?',
            'Какой вывод можно сделать на основе текста?',
            'Автор подразумевает, что:',
        ],
        'purpose': [
            'Какова цель этого текста?',
            'Зачем автор написал этот текст?',
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

        # Generate True/False style questions from sentences
        for i, sentence in enumerate(sentences[:num_questions]):
            q = cls._generate_true_false_question(sentence, sentences, i)
            if q:
                questions.append(q)

        # Shuffle
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
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 15]

    @classmethod
    def _truncate_sentence(cls, sentence: str, max_len: int = 100) -> str:
        """Truncate sentence at word boundary."""
        if len(sentence) <= max_len:
            return sentence
        # Find last space before max_len
        truncated = sentence[:max_len]
        last_space = truncated.rfind(' ')
        if last_space > max_len // 2:
            truncated = truncated[:last_space]
        return truncated.rstrip('.,;:') + '...'

    # Adjectives and their opposites for creating false statements
    OPPOSITE_ADJECTIVES = {
        'good': 'bad', 'bad': 'good', 'happy': 'sad', 'sad': 'happy',
        'big': 'small', 'small': 'big', 'old': 'young', 'young': 'old',
        'beautiful': 'ugly', 'kind': 'cruel', 'cruel': 'kind',
        'rich': 'poor', 'poor': 'rich', 'fast': 'slow', 'slow': 'fast',
        'hot': 'cold', 'cold': 'hot', 'light': 'dark', 'dark': 'light',
    }

    @classmethod
    def _make_false_statement(cls, sentence: str) -> Optional[str]:
        """Try to create a false version of a sentence by replacing adjectives."""
        words = sentence.split()
        if len(words) < 3:
            return None

        # Only use adjective replacement - it's safer and more reliable
        for i, word in enumerate(words):
            word_lower = word.lower().rstrip('.,!?')
            if word_lower in cls.OPPOSITE_ADJECTIVES:
                opposite = cls.OPPOSITE_ADJECTIVES[word_lower]
                # Preserve capitalization
                if word[0].isupper():
                    opposite = opposite.capitalize()
                # Preserve punctuation
                punct = word[len(word_lower):]
                words[i] = opposite + punct
                return ' '.join(words)

        # No safe transformation found
        return None

    @classmethod
    def _generate_true_false_question(cls, sentence: str, all_sentences: List[str], index: int) -> Optional[Dict]:
        """Generate a question asking if statement is true according to text."""
        if len(sentence) < 20:
            return None

        # Randomly decide if this will be a TRUE or FALSE question
        make_false = random.random() < 0.4  # 40% false questions

        if make_false:
            false_sentence = cls._make_false_statement(sentence)
            if false_sentence:
                clean_sentence = cls._truncate_sentence(false_sentence.strip('"\''), 120)
                correct_option = 'Нет, в тексте сказано другое'
                explanation = 'Это утверждение не соответствует тексту.'
            else:
                # Couldn't make false, use original
                clean_sentence = cls._truncate_sentence(sentence.strip('"\''), 120)
                correct_option = 'Да, это соответствует тексту'
                explanation = 'Это утверждение взято из текста.'
        else:
            clean_sentence = cls._truncate_sentence(sentence.strip('"\''), 120)
            correct_option = 'Да, это соответствует тексту'
            explanation = 'Это утверждение взято из текста.'

        # Question templates
        question_templates = [
            'Согласно тексту, верно ли следующее утверждение?',
            'Это утверждение соответствует тексту?',
            'Правда ли, что в тексте говорится следующее?',
        ]

        question = random.choice(question_templates) + f'\n\n«{clean_sentence}»'

        options = [
            'Да, это соответствует тексту',
            'Нет, в тексте сказано другое',
        ]
        random.shuffle(options)

        return {
            'question': question,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': explanation
        }

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
            distractors.append("Второстепенная деталь: " + sentences[-1][:30])
        distractors.extend([
            "Тема, не упомянутая в тексте",
            "Противоположность тому, о чём говорится в отрывке",
        ])

        options = [correct_option] + distractors[:3]
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'Этот вариант отражает главную мысль отрывка.'
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
            "Эта деталь не упоминается в тексте",
            "В тексте сказано противоположное",
            "Это другое событие, не из текста",
        ]

        options = [correct_option] + distractors[:3]
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'Эта деталь упоминается в тексте.'
        }

    @classmethod
    def _generate_vocabulary_question(cls, word: str, text: str) -> Optional[Dict]:
        """Generate a vocabulary in context question."""
        template = random.choice(cls.QUESTION_TEMPLATES['vocabulary']).format(word=word)

        # Simple synonyms/definitions (placeholder - would need dictionary in production)
        correct_option = f"Слово, связанное с '{word}'"

        distractors = [
            "Противоположное значение",
            "Не связанное по смыслу слово",
            "Похожее по звучанию, но другое по значению слово",
        ]

        options = [correct_option] + distractors
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': f'В данном контексте слово "{word}" имеет указанное значение.'
        }

    @classmethod
    def _generate_inference_question(cls, text: str, sentences: List[str]) -> Dict:
        """Generate an inference question."""
        template = random.choice(cls.QUESTION_TEMPLATES['inference'])

        # Create inference based on text content
        correct_option = "На основе описанных событий можно сделать вывод..."

        distractors = [
            "Текст противоречит этому утверждению",
            "В тексте нет доказательств этого",
            "Это противоречит тому, что подразумевает автор",
        ]

        options = [correct_option] + distractors
        random.shuffle(options)

        return {
            'question': template,
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'Этот вывод подтверждается содержанием текста.'
        }

    @classmethod
    def _generate_generic_question(cls, num: int) -> Dict:
        """Generate a generic question as fallback."""
        correct_option = 'Главную мысль отрывка'
        options = [
            correct_option,
            'Второстепенную деталь',
            'Тему, которая не упоминается',
            'Противоположность главной идеи'
        ]
        random.shuffle(options)

        return {
            'question': f'Вопрос {num}: Что можно понять из текста?',
            'options': options,
            'correct': options.index(correct_option),
            'explanation': 'Это связано с содержанием текста.'
        }

    @classmethod
    def _get_fallback_questions(cls) -> Dict[str, Any]:
        """Return fallback questions if text is too short."""
        return {
            'questions': [
                {
                    'question': 'Какова главная тема отрывка?',
                    'options': ['Главная тема', 'Второстепенная деталь', 'Не связанная тема', 'Противоположное значение'],
                    'correct': 0,
                    'explanation': 'Этот вопрос проверяет понимание главной мысли.'
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
            return 'вспомогательный глагол (have)'
        elif word_lower in ['is', 'are', 'was', 'were', 'been', 'being']:
            return 'глагол to be'
        elif word_lower in ['will', 'would', 'could', 'should', 'might', 'must', 'can', 'may']:
            return 'модальный глагол'
        elif word_lower in ['the', 'a', 'an']:
            return 'артикль'
        elif word_lower in ['in', 'on', 'at', 'by', 'for', 'with', 'to', 'from', 'of']:
            return 'предлог'
        elif word_lower in ['and', 'but', 'or', 'so', 'because', 'although', 'however']:
            return 'союз'
        elif word_lower in ['very', 'quite', 'really', 'just', 'only', 'even', 'also']:
            return 'наречие'
        elif word_lower in ['this', 'that', 'these', 'those']:
            return 'указательное местоимение'
        elif word_lower in ['who', 'which', 'what', 'where', 'when', 'how', 'why']:
            return 'вопросительное слово'
        else:
            return 'слово'

    @classmethod
    def _get_fallback_cloze(cls) -> Dict[str, Any]:
        """Return fallback cloze if text is too short."""
        return {
            'text': """The importance of reading cannot (1) ______ overstated. When we read, we not only gain knowledge (2) ______ also improve our vocabulary. Many successful people attribute their achievements (3) ______ the habit of reading regularly.

Reading fiction, (4) ______ particular, helps us develop empathy by allowing us to see the world through different perspectives. It has (5) ______ shown that regular readers are more likely to understand others.

Furthermore, reading is one of the (6) ______ effective ways to reduce stress. Studies have found that just six minutes of reading can reduce stress levels (7) ______ up to 68 percent. This makes it even more beneficial (8) ______ watching television.""",
            'gaps': [
                {'id': 1, 'answer': 'be', 'hint': 'вспомогательный глагол'},
                {'id': 2, 'answer': 'but', 'hint': 'союз'},
                {'id': 3, 'answer': 'to', 'hint': 'предлог'},
                {'id': 4, 'answer': 'in', 'hint': 'предлог (в выражении)'},
                {'id': 5, 'answer': 'been', 'hint': 'причастие прошедшего времени'},
                {'id': 6, 'answer': 'most', 'hint': 'превосходная степень'},
                {'id': 7, 'answer': 'by', 'hint': 'предлог'},
                {'id': 8, 'answer': 'than', 'hint': 'слово сравнения'}
            ]
        }
