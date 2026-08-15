"""
Quiz Service - quiz generation and management

Responsibilities:
- Question generation (multiple choice, fill-in-blank)
- Quiz scoring
- Quiz result tracking
"""
import random
from typing import Callable, Dict, List, Optional, Sequence, Set

from app.words.models import CollectionWords

# How many of a multiple-choice question's three distractors are drawn from the
# themed pool when one is supplied. The remaining slot is filled from the wider
# vocabulary on purpose: an all-in-theme question ("red" among four colours) is
# the point, but one outside option keeps a beginner from being stranded and
# lets sets with fewer than four words still produce a full question.
THEMED_DISTRACTOR_QUOTA = 2


def _answer_variants(text: Optional[str]) -> Set[str]:
    """Split a stored translation into its comparable variants.

    Translations are stored comma-separated («тень, оттенок»), so two options
    can look distinct as raw strings while naming the same thing. In the Colors
    set `shadow` is «тень» and `shade` is «тень, оттенок»: offered side by side,
    both are defensible answers but only one is graded correct. Comparing the
    variant sets — not the raw strings — is what keeps such a pair apart.
    """
    if not text:
        return set()
    return {part.strip().lower() for part in text.split(',') if part.strip()}


class QuizService:
    """Service for quiz operations"""

    QUESTION_TYPES = ['multiple_choice', 'fill_blank']

    @classmethod
    def generate_quiz_questions(
        cls,
        words: List[CollectionWords],
        count: int,
        get_audio_url: Optional[Callable] = None,
        distractor_pool: Optional[Sequence[CollectionWords]] = None,
    ) -> List[Dict]:
        """
        Generate quiz questions from words.

        Creates two questions per word (eng->rus and rus->eng) with
        a mix of multiple choice and fill-in-the-blank questions.

        Args:
            words: List of CollectionWords to generate questions from
            count: Number of questions to generate
            get_audio_url: Optional function to get audio URL for a word
            distractor_pool: Optional themed word list the wrong options should
                prefer. Supplied by the themed set quiz so a «Цвета» question
                offers colours; omitted elsewhere, where wrong options are drawn
                from the wider vocabulary as before.

        Returns:
            List of question dictionaries
        """
        if not words or count <= 0:
            return []

        questions = []

        # Ensure we don't try to create more questions than words
        count = min(count, len(words) * 2)

        # Create a list of all words for distractors (limit to avoid loading thousands)
        all_words = CollectionWords.query.filter(
            CollectionWords.russian_word != None,
            CollectionWords.russian_word != ''
        ).limit(500).all()

        # Create two questions per word (eng->rus and rus->eng)
        for word in words:
            if len(questions) >= count:
                break

            # Skip words without translations
            if not word.russian_word or word.russian_word.strip() == '':
                continue

            # Generate English to Russian question
            if len(questions) < count:
                question_type = random.choice(['multiple_choice', 'fill_blank'])

                if question_type == 'multiple_choice':
                    question = cls.create_multiple_choice_question(
                        word, all_words, 'eng_to_rus', get_audio_url,
                        pool_words=distractor_pool,
                    )
                else:
                    question = cls.create_fill_blank_question(
                        word, 'eng_to_rus', get_audio_url
                    )
                questions.append(question)

            # Generate Russian to English question - ALWAYS fill_blank
            # This guarantees the user must type the English word at least once
            if len(questions) < count:
                question = cls.create_fill_blank_question(
                    word, 'rus_to_eng', get_audio_url
                )
                questions.append(question)

        # Shuffle the questions
        random.shuffle(questions)

        # Limit to requested count
        return questions[:count]

    @staticmethod
    def _collect_distractors(
        word: CollectionWords,
        correct_answer: str,
        direction: str,
        themed_pool: Optional[Sequence[CollectionWords]],
        fallback_pool: Sequence[CollectionWords],
        needed: int = 3,
    ) -> List[str]:
        """Pick up to ``needed`` wrong options for a multiple-choice question.

        When ``themed_pool`` is given, the first ``THEMED_DISTRACTOR_QUOTA``
        options come from it and the rest from ``fallback_pool``; without it
        every option comes from ``fallback_pool``, which is the behaviour every
        pre-existing caller (decks, auto, linear plan) keeps.

        An option is rejected when it shares any translation variant with the
        correct answer or with an option already chosen — otherwise a question
        can offer the same meaning twice and have no single right answer.
        """
        attribute = 'russian_word' if direction == 'eng_to_rus' else 'english_word'

        taken = _answer_variants(correct_answer)
        chosen: List[str] = []

        def draw(pool: Sequence[CollectionWords], quota: int) -> None:
            if quota <= 0 or not pool:
                return
            candidates = list(pool)
            random.shuffle(candidates)
            for candidate in candidates:
                if len(chosen) >= needed or quota <= 0:
                    return
                if candidate.id == word.id:
                    continue
                value = getattr(candidate, attribute, None)
                if not value or not value.strip():
                    continue
                variants = _answer_variants(value)
                if not variants or variants & taken:
                    continue
                chosen.append(value)
                taken.update(variants)
                quota -= 1

        if themed_pool:
            draw(themed_pool, min(THEMED_DISTRACTOR_QUOTA, needed))
        draw(fallback_pool, needed - len(chosen))
        # A themed set can be richer than the sampled global pool; let it fill
        # any slot the fallback could not.
        if themed_pool and len(chosen) < needed:
            draw(themed_pool, needed - len(chosen))

        return chosen

    @staticmethod
    def create_multiple_choice_question(
        word: CollectionWords,
        all_words: List[CollectionWords],
        direction: str,
        get_audio_url: Optional[Callable] = None,
        pool_words: Optional[Sequence[CollectionWords]] = None,
    ) -> Dict:
        """
        Create a multiple choice question.

        Args:
            word: The word to create question for
            all_words: List of all words for creating distractors
            direction: 'eng_to_rus' or 'rus_to_eng'
            get_audio_url: Optional function to get audio URL
            pool_words: Optional themed pool the distractors should prefer

        Returns:
            Question dictionary
        """
        if direction == 'eng_to_rus':
            question_template = 'Переведите на русский:'
            question_text = word.english_word
            correct_answer = word.russian_word
        else:
            question_template = 'Переведите на английский:'
            question_text = word.russian_word
            correct_answer = word.english_word

        distractors = QuizService._collect_distractors(
            word=word,
            correct_answer=correct_answer,
            direction=direction,
            themed_pool=pool_words,
            fallback_pool=all_words,
        )

        # Ensure we have at least 3 distractors
        while len(distractors) < 3:
            if direction == 'eng_to_rus':
                distractors.append(f"[вариант {len(distractors) + 1}]")
            else:
                distractors.append(f"[option {len(distractors) + 1}]")

        # Create options and shuffle
        options = [correct_answer] + distractors[:3]  # Ensure exactly 4 options
        random.shuffle(options)

        # Audio for English word
        audio_url = None
        if direction == 'eng_to_rus' and get_audio_url:
            audio_url = get_audio_url(word)

        # Create hint
        first_word = correct_answer.split(',')[0].strip()
        hint = f"Начинается с: {first_word[0]}... ({len(first_word)} букв)"

        return {
            'id': f'mc_{word.id}_{direction}',
            'word_id': word.id,
            'type': 'multiple_choice',
            'text': question_text,
            'question_label': question_template,
            'options': options,
            'answer': correct_answer,
            'hint': hint,
            'audio_url': audio_url,
            'direction': direction
        }

    @staticmethod
    def create_fill_blank_question(
        word: CollectionWords,
        direction: str,
        get_audio_url: Optional[Callable] = None
    ) -> Dict:
        """
        Create a fill-in-the-blank question.

        Args:
            word: The word to create question for
            direction: 'eng_to_rus' or 'rus_to_eng'
            get_audio_url: Optional function to get audio URL

        Returns:
            Question dictionary
        """
        if direction == 'eng_to_rus':
            question_template = 'Введите перевод на русский:'
            question_text = word.english_word
            answer = word.russian_word
        else:
            question_template = 'Введите перевод на английский:'
            question_text = word.russian_word
            answer = word.english_word

        # Get acceptable alternative answers
        acceptable_answers = [answer]

        # If the answer contains commas, each part is an acceptable answer
        if ',' in answer:
            alternative_answers = [a.strip() for a in answer.split(',')]
            acceptable_answers.extend(alternative_answers)

        # Audio for English word
        audio_url = None
        if direction == 'eng_to_rus' and get_audio_url:
            audio_url = get_audio_url(word)

        # Create hint
        first_word = answer.split(',')[0].strip()
        hint = f"Начинается с: {first_word[0]}... ({len(first_word)} букв)"

        return {
            'id': f'fb_{word.id}_{direction}',
            'word_id': word.id,
            'type': 'fill_blank',
            'text': question_text,
            'question_label': question_template,
            'answer': answer,
            'acceptable_answers': acceptable_answers,
            'hint': hint,
            'audio_url': audio_url,
            'direction': direction
        }

    @staticmethod
    def calculate_quiz_score(total_questions: int, correct_answers: int,
                            time_taken_seconds: int) -> Dict:
        """
        Calculate quiz score and XP

        Args:
            total_questions: Total number of questions
            correct_answers: Number of correct answers
            time_taken_seconds: Time taken in seconds

        Returns:
            Dictionary with score, percentage, and XP awarded
        """
        if total_questions == 0:
            return {'score': 0, 'percentage': 0, 'xp_awarded': 0}

        percentage = (correct_answers / total_questions) * 100

        # Base XP: 10 per correct answer
        base_xp = correct_answers * 10

        # Bonus for perfect score
        if correct_answers == total_questions:
            base_xp += 50

        # Time bonus (faster = more XP)
        avg_time_per_question = time_taken_seconds / total_questions
        if avg_time_per_question < 5:  # Very fast
            base_xp = int(base_xp * 1.5)
        elif avg_time_per_question < 10:  # Fast
            base_xp = int(base_xp * 1.2)

        return {
            'score': correct_answers,
            'total': total_questions,
            'percentage': round(percentage, 1),
            'xp_awarded': base_xp,
            'time_taken': time_taken_seconds
        }
