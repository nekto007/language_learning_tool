"""
Final Test Generator

This module generates comprehensive final tests (32-36 questions) that combine
multiple task types for end-of-block assessment.
"""

import json
import logging
import random
from typing import Any, Dict, List, Optional

from app.books.models import Block, BlockVocab, Task
from app.utils.db import db

logger = logging.getLogger(__name__)


class FinalTestGenerator:
    """Generates comprehensive final tests for blocks"""

    def __init__(self):
        self.target_question_count = 34  # Target 32-36 questions
        self.min_questions = 32
        self.max_questions = 36

    def generate_final_test(self, block_id: int) -> Optional[Dict[str, Any]]:
        """Generate a comprehensive final test for a block"""
        try:
            block = Block.query.get_or_404(block_id)

            # Get existing tasks for this block
            existing_tasks = Task.query.filter_by(block_id=block_id).all()
            task_map = {task.task_type: task for task in existing_tasks}

            # Generate test sections
            test_sections = self._generate_test_sections(block, task_map)

            if not test_sections:
                logger.warning(f"Could not generate test sections for block {block_id}")
                return None

            # Compile all questions
            all_questions = []
            section_info = []

            for section in test_sections:
                section_info.append({
                    'type': section['type'],
                    'title': section['title'],
                    'question_count': len(section['questions']),
                    'instructions': section['instructions']
                })

                # Add section marker
                all_questions.append({
                    'type': 'section_header',
                    'title': section['title'],
                    'instructions': section['instructions']
                })

                # Add questions with numbering
                for i, question in enumerate(section['questions']):
                    question['section'] = section['type']
                    question['section_number'] = i + 1
                    question['overall_number'] = len(all_questions)
                    all_questions.append(question)

            # Create final test payload
            test_payload = {
                'type': 'final_test',
                'title': f'Final Test: Block {block.block_num}',
                'description': f'Comprehensive assessment covering all material from Block {block.block_num}',
                'instructions': self._get_test_instructions(),
                'sections': section_info,
                'questions': all_questions,
                'scoring': self._create_scoring_system(test_sections),
                'time_limit': self._calculate_time_limit(len(all_questions)),
                'metadata': {
                    'block_id': block_id,
                    'block_number': block.block_num,
                    'total_questions': len([q for q in all_questions if q['type'] != 'section_header']),
                    'total_sections': len(test_sections),
                    'grammar_focus': block.grammar_key,
                    'vocab_theme': block.focus_vocab
                }
            }

            actual_questions = len([q for q in all_questions if q['type'] != 'section_header'])
            logger.info(f"Generated final test with {actual_questions} questions for block {block_id}")
            return test_payload

        except Exception as e:
            logger.error(f"Error generating final test for block {block_id}: {str(e)}")
            return None

    def _generate_test_sections(self, block: Block, task_map: Dict[str, Task]) -> List[Dict[str, Any]]:
        """Generate different sections of the final test"""
        sections = []

        # Section 1: Vocabulary (8-10 questions)
        vocab_section = self._create_vocabulary_section(block, task_map)
        if vocab_section:
            sections.append(vocab_section)

        # Section 2: Reading Comprehension (6-8 questions)
        reading_section = self._create_reading_comprehension_section(block, task_map)
        if reading_section:
            sections.append(reading_section)

        # Section 3: Grammar & Language Use (8-10 questions)
        grammar_section = self._create_grammar_section(block, task_map)
        if grammar_section:
            sections.append(grammar_section)

        # Section 4: Text Completion (6-8 questions)
        completion_section = self._create_completion_section(block, task_map)
        if completion_section:
            sections.append(completion_section)

        # Section 5: Word Formation (4-6 questions)
        word_formation_section = self._create_word_formation_section(block, task_map)
        if word_formation_section:
            sections.append(word_formation_section)

        return sections

    def _create_vocabulary_section(self, block: Block, task_map: Dict[str, Task]) -> Optional[Dict[str, Any]]:
        """Create vocabulary section from vocabulary task"""
        if 'vocabulary' not in task_map:
            return self._create_basic_vocabulary_section(block)

        vocab_task = task_map['vocabulary']
        vocab_data = vocab_task.payload

        questions = []
        cards = vocab_data.get('cards', [])

        # Select 8-10 cards for testing
        selected_cards = random.sample(cards, min(10, len(cards))) if cards else []

        for i, card in enumerate(selected_cards):
            # Create multiple choice question
            question = {
                'id': f"vocab_{i + 1}",
                'type': 'multiple_choice',
                'question': f"What does '{card['front']}' mean?",
                'options': self._generate_vocab_options(card),
                'correct_answer': 0,  # Correct answer is always first, will be shuffled
                'points': 1,
                'explanation': card['back'].get('definition', '')
            }
            questions.append(question)

        # Shuffle options for each question
        for question in questions:
            self._shuffle_options(question)

        return {
            'type': 'vocabulary',
            'title': 'Vocabulary',
            'instructions': 'Choose the best definition for each word.',
            'questions': questions
        }

    def _create_basic_vocabulary_section(self, block: Block) -> Optional[Dict[str, Any]]:
        """Create basic vocabulary section from block vocabulary"""
        vocab_entries = BlockVocab.query.filter_by(block_id=block.id).order_by(
            BlockVocab.freq.desc()
        ).limit(10).all()

        if not vocab_entries:
            return None

        questions = []
        for i, entry in enumerate(vocab_entries):
            word = entry.word  # Use the relationship to get the word
            if not word:
                continue  # Skip if word not found

            question = {
                'id': f"vocab_{i + 1}",
                'type': 'multiple_choice',
                'question': f"Select the best definition for '{word.english_word}':",
                'options': [
                    f"A word meaning {word.english_word}",  # Placeholder - would need real definitions
                    f"A synonym for {word.english_word}",
                    f"An antonym for {word.english_word}",
                    f"Not related to {word.english_word}"
                ],
                'correct_answer': 0,
                'points': 1
            }
            questions.append(question)

        return {
            'type': 'vocabulary',
            'title': 'Vocabulary',
            'instructions': 'Choose the best definition for each word.',
            'questions': questions
        }

    def _create_reading_comprehension_section(self, block: Block, task_map: Dict[str, Task]) -> Optional[
        Dict[str, Any]]:
        """Create reading comprehension section"""

        # Use existing reading MCQ if available
        if 'reading_mcq' in task_map:
            mcq_task = task_map['reading_mcq']
            mcq_data = mcq_task.payload

            questions = mcq_data.get('questions', [])
            # Take first 6-8 questions
            selected_questions = questions[:8] if len(questions) >= 8 else questions

            # Reformat for final test
            formatted_questions = []
            for i, q in enumerate(selected_questions):
                formatted_q = {
                    'id': f"reading_{i + 1}",
                    'type': 'multiple_choice',
                    'question': q.get('question', ''),
                    'options': q.get('options', []),
                    'correct_answer': q.get('correct_answer', 0),
                    'points': 2,  # Reading questions worth more points
                    'explanation': q.get('explanation', '')
                }
                formatted_questions.append(formatted_q)

            return {
                'type': 'reading_comprehension',
                'title': 'Reading Comprehension',
                'instructions': 'Read the passage and answer the questions.',
                'passage': mcq_data.get('passage', ''),
                'questions': formatted_questions
            }

        return None

    def _create_grammar_section(self, block: Block, task_map: Dict[str, Task]) -> Optional[Dict[str, Any]]:
        """Create grammar section"""
        questions = []

        # Use keyword transformations if available
        if 'keyword_transform' in task_map:
            kt_task = task_map['keyword_transform']
            kt_data = kt_task.payload

            kt_questions = kt_data.get('questions', [])
            for i, q in enumerate(kt_questions[:6]):  # Take up to 6
                question = {
                    'id': f"grammar_{i + 1}",
                    'type': 'transformation',
                    'question': f"Complete the second sentence so that it has a similar meaning to the first sentence, using the word given. Use between 2-5 words.\n\n{q.get('sentence1', '')}\n{q.get('keyword', '').upper()}\n{q.get('sentence2', '')}",
                    'answer': q.get('answer', ''),
                    'points': 2,
                    'keyword': q.get('keyword', '')
                }
                questions.append(question)

        # Add some general grammar questions based on block focus
        if block.grammar_key and len(questions) < 8:
            additional_questions = self._generate_grammar_questions(block.grammar_key)
            questions.extend(additional_questions[:8 - len(questions)])

        if not questions:
            return None

        return {
            'type': 'grammar',
            'title': 'Grammar & Language Use',
            'instructions': 'Complete the sentences or transformations.',
            'questions': questions
        }

    def _create_completion_section(self, block: Block, task_map: Dict[str, Task]) -> Optional[Dict[str, Any]]:
        """Create text completion section from cloze test"""

        if 'open_cloze' not in task_map:
            return None

        cloze_task = task_map['open_cloze']
        cloze_data = cloze_task.payload

        questions = []
        gaps = cloze_data.get('gaps', [])

        for i, gap in enumerate(gaps[:8]):  # Take up to 8 gaps
            question = {
                'id': f"cloze_{i + 1}",
                'type': 'fill_blank',
                'question': f"Fill in the blank:\n\n{gap.get('context', '')}",
                'answer': gap.get('answer', ''),
                'points': 1,
                'position': gap.get('position', i + 1)
            }
            questions.append(question)

        if not questions:
            return None

        return {
            'type': 'completion',
            'title': 'Text Completion',
            'instructions': 'Fill in each blank with ONE word only.',
            'questions': questions
        }

    def _create_word_formation_section(self, block: Block, task_map: Dict[str, Task]) -> Optional[Dict[str, Any]]:
        """Create word formation section"""

        if 'word_formation' not in task_map:
            return None

        wf_task = task_map['word_formation']
        wf_data = wf_task.payload

        questions = []
        items = wf_data.get('items', [])

        for i, item in enumerate(items[:6]):  # Take up to 6 items
            question = {
                'id': f"word_form_{i + 1}",
                'type': 'word_formation',
                'question': f"Use the word given in capitals to form a word that fits in the gap.\n\n{item.get('sentence', '')}",
                'root_word': item.get('root_word', ''),
                'answer': item.get('answer', ''),
                'points': 1
            }
            questions.append(question)

        if not questions:
            return None

        return {
            'type': 'word_formation',
            'title': 'Word Formation',
            'instructions': 'Use the word in capitals to form a word that fits in the gap.',
            'questions': questions
        }

    def _generate_vocab_options(self, card: Dict[str, Any]) -> List[str]:
        """Generate multiple choice options for vocabulary"""
        correct_definition = card['back'].get('definition', '')
        translation = card['back'].get('translation', '')

        options = [correct_definition]  # Correct answer first

        # Generate distractors
        options.extend([
            f"A different meaning for {card['front']}",
            f"The opposite of {card['front']}",
            f"A similar word to {card['front']}"
        ])

        return options

    def _shuffle_options(self, question: Dict[str, Any]):
        """Shuffle multiple choice options and update correct answer"""
        if question['type'] != 'multiple_choice':
            return

        options = question['options'][:]
        correct_option = options[question['correct_answer']]

        random.shuffle(options)
        question['options'] = options
        question['correct_answer'] = options.index(correct_option)

    def _generate_grammar_questions(self, grammar_key: str) -> List[Dict[str, Any]]:
        """Generate basic grammar questions based on grammar focus"""

        # This is a simplified implementation
        # In practice, you'd have a database of grammar questions

        questions = []

        if 'Present_Perfect' in grammar_key:
            questions.append({
                'id': 'grammar_basic_1',
                'type': 'multiple_choice',
                'question': 'Choose the correct form: I _____ this book before.',
                'options': ['have read', 'has read', 'read', 'am reading'],
                'correct_answer': 0,
                'points': 1
            })

        if 'Reported_Speech' in grammar_key:
            questions.append({
                'id': 'grammar_basic_2',
                'type': 'multiple_choice',
                'question': 'She said that she _____ tired.',
                'options': ['was', 'is', 'will be', 'has been'],
                'correct_answer': 0,
                'points': 1
            })

        return questions

    def _create_scoring_system(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create scoring system for the test"""
        total_points = 0
        section_points = {}

        for section in sections:
            section_total = sum(q.get('points', 1) for q in section['questions'])
            section_points[section['type']] = section_total
            total_points += section_total

        return {
            'total_points': total_points,
            'section_points': section_points,
            'pass_percentage': 70,  # 70% to pass
            'grading_scale': {
                'A': 90,
                'B': 80,
                'C': 70,
                'D': 60,
                'F': 0
            }
        }

    def _calculate_time_limit(self, question_count: int) -> int:
        """Calculate time limit in minutes"""
        # Approximately 2 minutes per question, with minimum 45 minutes
        return max(45, question_count * 2)

    def _get_test_instructions(self) -> str:
        """Get general test instructions"""
        return """This is a comprehensive test covering all material from this block.

Instructions:
1. Read all questions carefully
2. Answer all questions - there is no penalty for guessing
3. For multiple choice, select the best answer
4. For fill-in-the-blank, write ONE word only
5. For word formation, use the root word to create the correct form
6. For transformations, use 2-5 words including the given keyword

You have sufficient time to complete the test. Good luck!"""

    def save_final_test_task(self, block_id: int) -> bool:
        """Generate and save final test task to database"""
        try:
            from app.books.models import TaskType

            # Check if final test already exists
            existing_task = Task.query.filter_by(
                block_id=block_id,
                task_type=TaskType.final_test
            ).first()

            # Generate final test
            test_payload = self.generate_final_test(block_id)

            if not test_payload:
                return False

            if existing_task:
                logger.info(f"Final test already exists for block {block_id}, updating...")
                existing_task.payload = test_payload
            else:
                # Create new task record
                task = Task(
                    block_id=block_id,
                    task_type=TaskType.final_test,
                    payload=test_payload
                )
                db.session.add(task)

            db.session.commit()

            logger.info(f"Saved final test for block {block_id}")
            return True

        except Exception as e:
            logger.error(f"Error saving final test for block {block_id}: {str(e)}")
            db.session.rollback()
            return False


# Utility functions

def generate_final_tests_for_book(book_id: int) -> int:
    """Generate final test tasks for all blocks in a book"""
    from app.books.models import Book

    book = Book.query.get(book_id)
    if not book:
        logger.error(f"Book {book_id} not found")
        return 0

    blocks = Block.query.filter_by(book_id=book_id).all()
    generator = FinalTestGenerator()

    success_count = 0
    for block in blocks:
        if generator.save_final_test_task(block.id):
            success_count += 1
        else:
            logger.warning(f"Failed to generate final test for block {block.id}")

    logger.info(f"Generated final tests for {success_count}/{len(blocks)} blocks")
    return success_count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate final tests")
    parser.add_argument("block_id", type=int, help="Block ID")
    parser.add_argument("--save", action="store_true", help="Save to database")
    parser.add_argument("--preview", action="store_true", help="Show preview")

    args = parser.parse_args()

    generator = FinalTestGenerator()

    if args.save:
        if generator.save_final_test_task(args.block_id):
            print(f"✅ Final test saved for block {args.block_id}")
        else:
            print("❌ Failed to save final test")

    elif args.preview:
        test = generator.generate_final_test(args.block_id)
        if test:
            print(f"Title: {test['title']}")
            print(f"Total questions: {test['metadata']['total_questions']}")
            print(f"Time limit: {test['time_limit']} minutes")
            print(f"Sections: {test['metadata']['total_sections']}")
            print("\nSection breakdown:")
            for section in test['sections']:
                print(f"  - {section['title']}: {section['question_count']} questions")
        else:
            print("❌ Failed to generate final test")

    else:
        test = generator.generate_final_test(args.block_id)
        if test:
            print(json.dumps(test, indent=2, ensure_ascii=False))
        else:
            print("❌ Failed to generate final test")
