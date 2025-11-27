"""
Task Generators for Book Courses

Generates various task types (reading_mcq, match_headings, open_cloze, etc.)
for book course blocks based on chapter content.
"""

import logging
import random
import re
from typing import Any, Dict, List, Optional

from app.books.models import Block, BlockVocab, Task, TaskType
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)


def generate_all_task_types(block: Block) -> List[Task]:
    """
    Generate all task types for a block.

    Args:
        block: Block to generate tasks for

    Returns:
        List of created Task objects
    """
    tasks = []

    # Get block text and vocabulary
    block_text = _get_block_text(block)
    block_vocab = _get_block_vocabulary(block)

    if not block_text:
        logger.warning(f"No text found for block {block.id}")
        return tasks

    generators = [
        (TaskType.vocabulary, _generate_vocabulary_task),
        (TaskType.reading_passage, _generate_reading_passage_task),
        (TaskType.reading_mcq, _generate_reading_mcq_task),
        (TaskType.match_headings, _generate_match_headings_task),
        (TaskType.open_cloze, _generate_open_cloze_task),
        (TaskType.word_formation, _generate_word_formation_task),
        (TaskType.keyword_transform, _generate_keyword_transform_task),
        (TaskType.grammar_sheet, _generate_grammar_sheet_task),
        (TaskType.final_test, _generate_final_test_task),
    ]

    for task_type, generator_func in generators:
        try:
            # Check if task already exists
            existing = Task.query.filter_by(block_id=block.id, task_type=task_type).first()
            if existing:
                tasks.append(existing)
                continue

            payload = generator_func(block, block_text, block_vocab)
            if payload:
                task = Task(
                    block_id=block.id,
                    task_type=task_type,
                    payload=payload
                )
                db.session.add(task)
                tasks.append(task)
                logger.info(f"Generated {task_type.value} task for block {block.id}")

        except Exception as e:
            logger.error(f"Error generating {task_type.value} task: {str(e)}")

    return tasks


def _get_block_text(block: Block) -> str:
    """Get combined text from all chapters in block"""
    texts = []
    for chapter in sorted(block.chapters, key=lambda c: c.chap_num):
        if chapter.text_raw:
            texts.append(chapter.text_raw)
    return '\n\n'.join(texts)


def _get_block_vocabulary(block: Block) -> List[Dict[str, Any]]:
    """Get vocabulary entries for block with word details"""
    vocab = []
    entries = BlockVocab.query.filter_by(block_id=block.id).all()

    for entry in entries:
        word = CollectionWords.query.get(entry.word_id)
        if word:
            vocab.append({
                'id': word.id,
                'english': word.english_word,
                'russian': word.russian_word,
                'frequency': entry.freq,
                'level': word.level,
                'sentences': word.sentences
            })

    return vocab


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences"""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 20]


def _split_into_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs"""
    paragraphs = text.split('\n\n')
    return [p.strip() for p in paragraphs if p.strip() and len(p.strip()) > 50]


# Task Type Generators

def _generate_vocabulary_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate vocabulary flashcard task.
    Payload: {cards: [{front, back: {translation, examples}}]}
    """
    if not vocab:
        return None

    cards = []
    for word_data in vocab[:20]:  # Max 20 cards
        # Find example sentence in text
        example = _find_word_in_context(word_data['english'], text)

        card = {
            'front': word_data['english'],
            'back': {
                'translation': word_data['russian'] or '',
                'examples': [example] if example else [],
                'level': word_data.get('level', ''),
            }
        }
        cards.append(card)

    return {
        'cards': cards,
        'total_cards': len(cards),
        'estimated_time': 15  # minutes
    }


def _generate_reading_passage_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate reading passage task.
    Payload: {text, word_count, vocabulary_highlights}
    """
    # Get first 750 words as passage
    words = text.split()
    passage_words = words[:750] if len(words) > 750 else words

    # Find sentence boundary near 750 words
    passage_text = ' '.join(passage_words)
    last_period = passage_text.rfind('.')
    if last_period > 500:
        passage_text = passage_text[:last_period + 1]

    # Create vocabulary highlights
    vocab_words = [v['english'].lower() for v in vocab]

    return {
        'text': passage_text,
        'word_count': len(passage_text.split()),
        'vocabulary_words': vocab_words,
        'estimated_time': 20  # minutes
    }


def _generate_reading_mcq_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate multiple choice questions about the text.
    Payload: {questions: [{text, options, correct, explanation}]}
    """
    sentences = _split_into_sentences(text)
    if len(sentences) < 10:
        return None

    questions = []

    # Generate questions based on key sentences
    for i, sentence in enumerate(sentences[:30]):  # Check first 30 sentences
        if len(questions) >= 10:
            break

        # Skip very short or very long sentences
        if len(sentence.split()) < 8 or len(sentence.split()) > 40:
            continue

        # Create question about the sentence
        question = _create_comprehension_question(sentence, i)
        if question:
            questions.append(question)

    # If not enough questions, create general ones
    while len(questions) < 10:
        questions.append({
            'text': f'According to the passage, what is discussed in paragraph {len(questions) + 1}?',
            'options': [
                'Main character development',
                'Setting description',
                'Plot advancement',
                'Theme introduction'
            ],
            'correct': random.randint(0, 3),
            'explanation': 'This question tests general comprehension of the text structure.'
        })

    return {
        'questions': questions[:10],
        'total_questions': 10,
        'estimated_time': 15,
        'pass_score': 70
    }


def _generate_match_headings_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate heading matching task.
    Payload: {paragraphs: [{id, text}], headings: [{id, text}]}
    """
    paragraphs = _split_into_paragraphs(text)
    if len(paragraphs) < 6:
        return None

    # Select 6 paragraphs
    selected_paragraphs = []
    for i, para in enumerate(paragraphs[:8]):
        if len(selected_paragraphs) >= 6:
            break
        if len(para.split()) >= 30:  # At least 30 words
            selected_paragraphs.append({
                'id': len(selected_paragraphs) + 1,
                'text': para[:500] if len(para) > 500 else para  # Truncate long paragraphs
            })

    if len(selected_paragraphs) < 6:
        return None

    # Generate 8 headings (6 correct + 2 distractors)
    headings = []
    for i, para in enumerate(selected_paragraphs):
        heading = _generate_paragraph_heading(para['text'])
        headings.append({
            'id': chr(65 + i),  # A, B, C, etc.
            'text': heading,
            'correct_for': para['id']
        })

    # Add 2 distractor headings
    distractors = [
        'The importance of daily routines',
        'Understanding modern technology'
    ]
    for i, d in enumerate(distractors):
        headings.append({
            'id': chr(65 + len(selected_paragraphs) + i),
            'text': d,
            'correct_for': None
        })

    random.shuffle(headings)

    return {
        'paragraphs': selected_paragraphs,
        'headings': headings,
        'total_paragraphs': len(selected_paragraphs),
        'total_headings': len(headings),
        'estimated_time': 10
    }


def _generate_open_cloze_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate open cloze (fill in the blank) task.
    Payload: {text, gaps: [{position, answer, hint}]}
    """
    sentences = _split_into_sentences(text)
    if len(sentences) < 8:
        return None

    # Select sentences and create gaps
    gaps = []
    cloze_text_parts = []

    # Words suitable for gaps
    gap_words = ['the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'with', 'by',
                 'is', 'are', 'was', 'were', 'has', 'have', 'had', 'been',
                 'which', 'who', 'that', 'this', 'these', 'those',
                 'not', 'no', 'so', 'as', 'if', 'but', 'or', 'and']

    gap_count = 0
    for sentence in sentences[:20]:
        if gap_count >= 8:
            break

        words = sentence.split()
        for i, word in enumerate(words):
            if gap_count >= 8:
                break

            clean_word = word.lower().strip('.,!?;:')
            if clean_word in gap_words and random.random() > 0.7:
                gap_count += 1
                gaps.append({
                    'id': gap_count,
                    'answer': clean_word,
                    'hint': f'First letter: {clean_word[0].upper()}'
                })
                words[i] = f'({gap_count}) ______'

        cloze_text_parts.append(' '.join(words))

    if len(gaps) < 8:
        return None

    return {
        'text': ' '.join(cloze_text_parts),
        'gaps': gaps[:8],
        'total_gaps': 8,
        'estimated_time': 12,
        'pass_score': 70
    }


def _generate_word_formation_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate word formation task.
    Payload: {sentences: [{text, base_word, answer, position}]}
    """
    # Word families for word formation
    word_families = {
        'happy': ['happiness', 'unhappy', 'happily', 'unhappiness'],
        'success': ['successful', 'successfully', 'unsuccessful'],
        'beauty': ['beautiful', 'beautifully', 'beautify'],
        'care': ['careful', 'carefully', 'careless', 'carelessly'],
        'help': ['helpful', 'helpless', 'helpfully'],
        'hope': ['hopeful', 'hopeless', 'hopefully'],
        'danger': ['dangerous', 'dangerously', 'endanger'],
        'create': ['creative', 'creation', 'creativity', 'creator'],
        'decide': ['decision', 'decisive', 'decisively', 'indecisive'],
        'believe': ['belief', 'believable', 'unbelievable', 'believer'],
    }

    sentences = _split_into_sentences(text)
    items = []

    for sentence in sentences[:30]:
        if len(items) >= 8:
            break

        sentence_lower = sentence.lower()
        for base_word, forms in word_families.items():
            for form in forms:
                if form in sentence_lower:
                    items.append({
                        'sentence': sentence.replace(form, f'______ ({base_word.upper()})'),
                        'base_word': base_word.upper(),
                        'answer': form,
                        'hint': f'Change the word form of {base_word}'
                    })
                    break
            if len(items) >= 8:
                break

    # Fill with template items if not enough found
    while len(items) < 8:
        items.append({
            'sentence': 'The ______ (BEAUTY) of nature is breathtaking.',
            'base_word': 'BEAUTY',
            'answer': 'beauty',
            'hint': 'No change needed or use noun form'
        })

    return {
        'items': items[:8],
        'total_items': 8,
        'estimated_time': 10,
        'pass_score': 70
    }


def _generate_keyword_transform_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate key word transformation task.
    Payload: {sentences: [{original, keyword, target, answer}]}
    """
    # Template transformations
    transformations = [
        {
            'original': 'I started learning English three years ago.',
            'keyword': 'BEEN',
            'target': 'I ____________ English for three years.',
            'answer': 'have been learning'
        },
        {
            'original': 'They said the meeting was cancelled.',
            'keyword': 'TOLD',
            'target': 'They ____________ the meeting was cancelled.',
            'answer': 'told us/me that'
        },
        {
            'original': "It's possible that she forgot about the appointment.",
            'keyword': 'MAY',
            'target': 'She ____________ about the appointment.',
            'answer': 'may have forgotten'
        },
        {
            'original': 'I regret not studying harder for the exam.',
            'keyword': 'WISH',
            'target': 'I ____________ harder for the exam.',
            'answer': 'wish I had studied'
        },
        {
            'original': "It wasn't necessary for you to come so early.",
            'keyword': 'NEED',
            'target': 'You ____________ come so early.',
            'answer': "didn't need to/needn't have"
        },
        {
            'original': 'The last time I saw her was in 2020.',
            'keyword': 'SINCE',
            'target': 'I ____________ 2020.',
            'answer': "haven't seen her since"
        },
    ]

    return {
        'sentences': transformations,
        'total_sentences': len(transformations),
        'estimated_time': 12,
        'pass_score': 70,
        'instructions': 'Complete the second sentence using the keyword. Use between 2-5 words.'
    }


def _generate_grammar_sheet_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate grammar mini-lesson task.
    Payload: {topic, explanation, examples, exercises}
    """
    grammar_focus = block.grammar_key or 'Present_Perfect'

    # Grammar explanations based on common topics
    grammar_topics = {
        'Present_Perfect': {
            'topic': 'Present Perfect Tense',
            'explanation': '''The Present Perfect is used to:
1. Talk about experiences without a specific time
2. Describe actions that started in the past and continue to now
3. Talk about recent actions with a present result

Formation: have/has + past participle''',
            'examples': [
                'I have visited Paris twice.',
                'She has lived here since 2010.',
                'They have just finished their homework.'
            ]
        },
        'Past_Simple': {
            'topic': 'Past Simple Tense',
            'explanation': '''The Past Simple is used for:
1. Completed actions at a specific time in the past
2. A series of completed actions
3. Past habits or states

Formation: verb + -ed (or irregular form)''',
            'examples': [
                'I visited Paris last year.',
                'She walked to school every day.',
                'They finished their homework an hour ago.'
            ]
        },
        'Reported_Speech': {
            'topic': 'Reported Speech',
            'explanation': '''Reported Speech (Indirect Speech) is used to tell someone what another person said.

Key changes:
- Pronouns change
- Tenses shift back
- Time/place expressions change''',
            'examples': [
                'Direct: "I am tired." → Reported: She said she was tired.',
                'Direct: "I will help you." → Reported: He said he would help me.',
            ]
        }
    }

    # Get topic or use default
    topic_key = grammar_focus.replace(' ', '_')
    topic_data = grammar_topics.get(topic_key, grammar_topics['Present_Perfect'])

    exercises = [
        {
            'question': f'Which sentence correctly uses the {topic_data["topic"]}?',
            'options': [
                'I have seen him yesterday.',
                'I have seen him before.',
                'I have seen him last week.',
                'I seen him already.'
            ],
            'correct': 1,
            'explanation': 'Present Perfect is used for experiences without specific time.'
        },
        {
            'question': 'Complete: She _____ here for five years.',
            'options': ['lives', 'has lived', 'lived', 'is living'],
            'correct': 1,
            'explanation': 'Use Present Perfect with "for" + period of time.'
        },
        {
            'question': 'Which is grammatically correct?',
            'options': [
                'I have went to the store.',
                'I have been to the store.',
                'I have go to the store.',
                'I has been to the store.'
            ],
            'correct': 1,
            'explanation': 'Use "been" as past participle of "go" for experiences.'
        },
        {
            'question': 'Choose the correct form:',
            'options': [
                'They have already ate.',
                'They have already eaten.',
                'They already have eaten.',
                'They have ate already.'
            ],
            'correct': 1,
            'explanation': '"Eaten" is the correct past participle of "eat".'
        }
    ]

    return {
        'topic': topic_data['topic'],
        'explanation': topic_data['explanation'],
        'examples': topic_data['examples'],
        'exercises': exercises,
        'estimated_time': 18,
        'pass_score': 70
    }


def _generate_final_test_task(block: Block, text: str, vocab: List[Dict]) -> Optional[Dict]:
    """
    Generate comprehensive final test.
    Payload: {sections: [{type, questions}], total_questions, pass_score}
    """
    sections = []

    # Section 1: Vocabulary (10 questions)
    vocab_questions = []
    for word_data in vocab[:10]:
        vocab_questions.append({
            'type': 'vocabulary',
            'question': f'What is the meaning of "{word_data["english"]}"?',
            'options': [
                word_data['russian'] or 'meaning 1',
                'incorrect meaning 2',
                'incorrect meaning 3',
                'incorrect meaning 4'
            ],
            'correct': 0
        })
    sections.append({
        'name': 'Vocabulary',
        'questions': vocab_questions
    })

    # Section 2: Grammar (8 questions)
    grammar_questions = [
        {
            'type': 'grammar',
            'question': 'Choose the correct form: I _____ this book since Monday.',
            'options': ['read', 'have read', 'am reading', 'was reading'],
            'correct': 1
        },
        {
            'type': 'grammar',
            'question': 'Choose the correct form: She _____ to school every day.',
            'options': ['go', 'goes', 'going', 'gone'],
            'correct': 1
        }
    ]
    # Fill remaining grammar questions
    while len(grammar_questions) < 8:
        grammar_questions.append({
            'type': 'grammar',
            'question': f'Grammar question {len(grammar_questions) + 1}',
            'options': ['option A', 'option B', 'option C', 'option D'],
            'correct': 0
        })
    sections.append({
        'name': 'Grammar',
        'questions': grammar_questions[:8]
    })

    # Section 3: Reading comprehension (8 questions)
    reading_questions = []
    sentences = _split_into_sentences(text)
    for i, sentence in enumerate(sentences[:8]):
        reading_questions.append({
            'type': 'reading',
            'question': f'According to the text, is this statement true or false: "{sentence[:100]}..."',
            'options': ['True', 'False', 'Not mentioned', 'Partially true'],
            'correct': random.randint(0, 3)
        })
    sections.append({
        'name': 'Reading Comprehension',
        'questions': reading_questions
    })

    # Section 4: Use of English (10 questions)
    use_questions = []
    for i in range(10):
        use_questions.append({
            'type': 'use_of_english',
            'question': f'Fill in the blank: Question {i + 1}',
            'options': ['option A', 'option B', 'option C', 'option D'],
            'correct': random.randint(0, 3)
        })
    sections.append({
        'name': 'Use of English',
        'questions': use_questions
    })

    total_questions = sum(len(s['questions']) for s in sections)

    return {
        'sections': sections,
        'total_questions': total_questions,
        'estimated_time': 25,
        'pass_score': 70,
        'instructions': 'Complete all sections. You need 70% to pass this module.'
    }


# Helper functions

def _find_word_in_context(word: str, text: str) -> Optional[str]:
    """Find a sentence containing the word"""
    sentences = _split_into_sentences(text)
    pattern = r'\b' + re.escape(word) + r'\b'

    for sentence in sentences:
        if re.search(pattern, sentence, re.IGNORECASE):
            if len(sentence) > 150:
                sentence = sentence[:147] + '...'
            return sentence

    return None


def _create_comprehension_question(sentence: str, index: int) -> Optional[Dict]:
    """Create a comprehension question from a sentence"""
    # Simple question generation based on sentence structure
    words = sentence.split()

    if len(words) < 8:
        return None

    # Find a key word to ask about
    key_words = [w for w in words if len(w) > 4 and w.isalpha()]
    if not key_words:
        return None

    key_word = random.choice(key_words[:5])

    return {
        'text': f'Based on the text, what can we understand about "{key_word}"?',
        'options': [
            f'It relates to the main topic',
            f'It is mentioned in a negative context',
            f'It is used metaphorically',
            f'It is not directly relevant'
        ],
        'correct': 0,
        'explanation': f'This question tests understanding of how "{key_word}" is used in context.'
    }


def _generate_paragraph_heading(paragraph: str) -> str:
    """Generate a heading for a paragraph"""
    # Simple approach: use first few significant words
    words = paragraph.split()[:10]
    significant = [w for w in words if len(w) > 3 and w.isalpha()]

    if significant:
        return ' '.join(significant[:4]).title()

    return "General Discussion"
