"""
Vocabulary Extractor for Book Courses

Extracts vocabulary words from book chapters and links them to the CollectionWords database.
Used by BookCourseGenerator to populate BlockVocab entries.
"""

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from app.books.models import Block, BlockVocab, Chapter
from app.utils.db import db
from app.words.models import CollectionWords

logger = logging.getLogger(__name__)

# Common English stop words to exclude
STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after',
    'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once',
    'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
    'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should',
    'now', 'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you',
    'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself',
    'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them',
    'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this',
    'that', 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing',
    'would', 'could', 'ought', 'because', 'as', 'until', 'while', 'if',
    'said', 'went', 'got', 'get', 'go', 'come', 'came', 'make', 'made',
    'like', 'know', 'knew', 'think', 'thought', 'see', 'saw', 'want', 'give',
    'gave', 'take', 'took', 'tell', 'told', 'look', 'looked', 'ask', 'asked',
    'seem', 'seemed', 'let', 'put', 'say', 'yes', 'oh', 'well', 'mr', 'mrs',
    'miss', 'sir', 'one', 'two', 'three', 'first', 'last', 'long', 'little',
    'old', 'new', 'good', 'great', 'much', 'every', 'even', 'back', 'still',
    'also', 'over', 'down', 'out', 'off', 'away', 'never', 'always', 'must',
    'might', 'may', 'shall', 'cannot', 'couldn', 'didn', 'doesn', 'hadn',
    'hasn', 'haven', 'isn', 'weren', 'won', 'wouldn', 'ain', 'll', 've', 're',
    'd', 'm', 'o', 'y', 'ma', 'chapter'
}


class VocabularyExtractor:
    """Extracts and manages vocabulary for book blocks"""

    # CEFR level ordering for filtering
    CEFR_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    DEFAULT_LEVEL = 'B1'

    def __init__(self, book_id: int, target_level: str = None):
        """
        Initialize the vocabulary extractor.

        Args:
            book_id: ID of the book
            target_level: Target CEFR level for vocabulary filtering (A1-C2)
        """
        self.book_id = book_id
        self.target_level = target_level or self.DEFAULT_LEVEL
        self._word_cache: Dict[str, CollectionWords] = {}
        self._load_word_cache()

    def _load_word_cache(self):
        """Pre-load all collection words for faster lookup"""
        words = CollectionWords.query.all()
        for word in words:
            self._word_cache[word.english_word.lower()] = word
        logger.info(f"Loaded {len(self._word_cache)} words into cache")

    def extract_vocabulary_for_all_blocks(self, max_words_per_block: int = 20) -> bool:
        """
        Extract vocabulary for all blocks in the book.

        Args:
            max_words_per_block: Maximum number of vocabulary words per block

        Returns:
            True if extraction was successful
        """
        try:
            blocks = Block.query.filter_by(book_id=self.book_id).order_by(Block.block_num).all()

            if not blocks:
                logger.warning(f"No blocks found for book {self.book_id}")
                return False

            success_count = 0
            used_words: Set[int] = set()  # Track words already used in previous blocks

            for block in blocks:
                logger.info(f"Extracting vocabulary for block {block.block_num}")

                # Get all text from chapters in this block
                chapter_text = self._get_block_text(block)
                if not chapter_text:
                    logger.warning(f"No text found for block {block.block_num}")
                    continue

                # Extract and rank words
                word_frequencies = self._extract_words_from_text(chapter_text)

                # Find matching words in database
                matched_words = self._find_matching_words(word_frequencies, used_words, max_words_per_block)

                if matched_words:
                    # Create BlockVocab entries
                    self._create_block_vocab_entries(block.id, matched_words)

                    # Track used words to avoid repetition
                    for word_id, _ in matched_words:
                        used_words.add(word_id)

                    success_count += 1
                    logger.info(f"Added {len(matched_words)} vocabulary words to block {block.block_num}")
                else:
                    logger.warning(f"No matching vocabulary found for block {block.block_num}")

            db.session.commit()
            logger.info(f"Vocabulary extracted for {success_count}/{len(blocks)} blocks")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error extracting vocabulary: {str(e)}")
            db.session.rollback()
            return False

    def _get_block_text(self, block: Block) -> str:
        """Get combined text from all chapters in a block"""
        texts = []
        for chapter in block.chapters:
            if chapter.text_raw:
                texts.append(chapter.text_raw)
        return ' '.join(texts)

    def _extract_words_from_text(self, text: str) -> Counter:
        """
        Extract words from text and count their frequencies.

        Args:
            text: Raw text to process

        Returns:
            Counter with word frequencies
        """
        # Clean and tokenize text
        text = text.lower()
        # Remove punctuation but keep apostrophes within words
        text = re.sub(r"[^\w\s']", ' ', text)
        # Split into words
        words = text.split()

        # Filter and count
        word_counts = Counter()
        for word in words:
            # Clean word
            word = word.strip("'")

            # Skip short words, numbers, and stop words
            if (len(word) < 3 or
                    word.isdigit() or
                    word in STOP_WORDS or
                    not word.isalpha()):
                continue

            word_counts[word] += 1

        return word_counts

    def _get_level_index(self, level: str) -> int:
        """Get numeric index for CEFR level for comparison"""
        if level and level in self.CEFR_LEVELS:
            return self.CEFR_LEVELS.index(level)
        return self.CEFR_LEVELS.index(self.DEFAULT_LEVEL)  # Default to B1

    def _find_matching_words(
            self,
            word_frequencies: Counter,
            used_words: Set[int],
            max_words: int
    ) -> List[Tuple[int, int]]:
        """
        Find words that exist in CollectionWords database, filtered by CEFR level.

        Words are prioritized as follows:
        1. Words at or below the target CEFR level
        2. Words closest to the target level (preferring target level itself)
        3. By frequency in the text

        Args:
            word_frequencies: Counter with word frequencies
            used_words: Set of word IDs already used in other blocks
            max_words: Maximum number of words to return

        Returns:
            List of tuples (word_id, frequency)
        """
        target_idx = self._get_level_index(self.target_level)

        # Collect all matching words with their level info
        candidates = []

        for word, freq in word_frequencies.most_common():
            # Check if word exists in database
            if word in self._word_cache:
                db_word = self._word_cache[word]

                # Skip if already used
                if db_word.id in used_words:
                    continue

                # Get word's CEFR level
                word_level = getattr(db_word, 'level', None) or self.DEFAULT_LEVEL
                word_level_idx = self._get_level_index(word_level)

                # Only include words at or below target level
                # This ensures beginners don't get advanced vocabulary
                if word_level_idx <= target_idx:
                    # Calculate priority: closer to target level = better
                    # Words at exactly target level get priority 0
                    # Lower levels get positive priority (less preferred)
                    level_distance = abs(target_idx - word_level_idx)

                    candidates.append({
                        'word_id': db_word.id,
                        'freq': freq,
                        'level_distance': level_distance,
                        'level': word_level
                    })

        # Sort candidates:
        # 1. By level distance (closer to target level first)
        # 2. By frequency (higher frequency first)
        candidates.sort(key=lambda x: (x['level_distance'], -x['freq']))

        # Take top max_words
        matched_words = [(c['word_id'], c['freq']) for c in candidates[:max_words]]

        if matched_words:
            logger.info(
                f"Found {len(matched_words)} words for level {self.target_level} "
                f"(target index: {target_idx})"
            )

        return matched_words

    def _create_block_vocab_entries(self, block_id: int, matched_words: List[Tuple[int, int]]) -> bool:
        """
        Create BlockVocab entries for matched words.

        Args:
            block_id: ID of the block
            matched_words: List of (word_id, frequency) tuples

        Returns:
            True if successful
        """
        try:
            # Clear existing entries for this block
            BlockVocab.query.filter_by(block_id=block_id).delete()

            for word_id, freq in matched_words:
                entry = BlockVocab(
                    block_id=block_id,
                    word_id=word_id,
                    freq=freq
                )
                db.session.add(entry)

            return True

        except Exception as e:
            logger.error(f"Error creating BlockVocab entries: {str(e)}")
            return False

    def extract_vocabulary_for_single_block(self, block_id: int, max_words: int = 20) -> List[CollectionWords]:
        """
        Extract vocabulary for a single block.

        Args:
            block_id: ID of the block
            max_words: Maximum number of words

        Returns:
            List of CollectionWords objects
        """
        block = Block.query.get(block_id)
        if not block:
            return []

        chapter_text = self._get_block_text(block)
        if not chapter_text:
            return []

        word_frequencies = self._extract_words_from_text(chapter_text)
        matched_words = self._find_matching_words(word_frequencies, set(), max_words)

        self._create_block_vocab_entries(block_id, matched_words)
        db.session.commit()

        return [self._word_cache[CollectionWords.query.get(wid).english_word.lower()]
                for wid, _ in matched_words
                if wid in [w.id for w in CollectionWords.query.filter(
                CollectionWords.id.in_([m[0] for m in matched_words])).all()]]

    def get_context_sentence(self, word: str, text: str) -> Optional[str]:
        """
        Find a sentence containing the given word.

        Args:
            word: Word to find
            text: Text to search in

        Returns:
            Sentence containing the word, or None
        """
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)

        word_pattern = r'\b' + re.escape(word) + r'\b'

        for sentence in sentences:
            if re.search(word_pattern, sentence, re.IGNORECASE):
                # Clean up the sentence
                sentence = sentence.strip()
                if len(sentence) > 200:
                    # Truncate long sentences
                    sentence = sentence[:197] + '...'
                return sentence

        return None
