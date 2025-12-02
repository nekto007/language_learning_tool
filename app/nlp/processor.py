"""
Natural language processing module for English texts.
Includes functions for tokenization, lemmatization, and word processing.
"""
import logging
from typing import List, Set, Tuple

import nltk
from bs4 import BeautifulSoup
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer

from app.nlp.setup import initialize_nltk

logger = logging.getLogger(__name__)


def get_wordnet_pos(treebank_tag: str) -> str:
    """
    Converts NLTK POS tag to WordNet format.

    Args:
        treebank_tag (str): POS tag from NLTK.

    Returns:
        str: Corresponding WordNet POS tag.
    """
    if treebank_tag.startswith("J"):
        return wordnet.ADJ
    elif treebank_tag.startswith("V"):
        return wordnet.VERB
    elif treebank_tag.startswith("N"):
        return wordnet.NOUN
    elif treebank_tag.startswith("R"):
        return wordnet.ADV
    else:
        # By default, use NOUN for lemmatization
        return wordnet.NOUN


def extract_text_from_html(html_content: str, selector: str = None) -> str:
    """
    Extracts text from HTML content using the specified CSS selector.

    Args:
        html_content (str): HTML content.
        selector (str, optional): CSS selector. Defaults to None.
            If None, tries to use standard selectors.

    Returns:
        str: Extracted text.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    if selector:
        element = soup.select_one(selector)
    else:
        # Try various selectors
        element = (
                soup.find("article", {"class": "page-content"}) or
                soup.find("div", {"class": "entrytext"}) or
                soup.find("div", {"class": "content"})
        )

    if not element:
        logger.warning("Could not find suitable element in HTML")
        # Use all text from body if no suitable element was found
        return soup.body.text if soup.body else ""

    return element.text


def expand_contractions(text: str) -> str:
    """
    Expands common English contractions to full forms.
    This ensures words like can't -> can not are properly tokenized.
    """
    contractions = {
        "can't": "can not",
        "won't": "will not",
        "n't": " not",  # general: don't, doesn't, didn't, etc.
        "'ll": " will",
        "'re": " are",
        "'ve": " have",
        "'m": " am",
        "'d": " would",
        "let's": "let us",
    }
    text_lower = text
    for contraction, expansion in contractions.items():
        text_lower = text_lower.replace(contraction, expansion)
        text_lower = text_lower.replace(contraction.capitalize(), expansion)
        text_lower = text_lower.replace(contraction.upper(), expansion.upper())
    return text_lower


def tokenize_and_filter(text: str, stop_words: Set[str]) -> List[str]:
    """
    Tokenizes text and filters stop words and non-alphabetic tokens.

    Args:
        text (str): Source text.
        stop_words (Set[str]): Set of stop words.

    Returns:
        List[str]: List of tokens.
    """
    # Expand contractions before tokenizing
    text = expand_contractions(text)

    words = nltk.word_tokenize(text)
    # Filter only alphabetic characters and convert to lowercase
    words = [word.lower() for word in words if word.isalpha()]
    stop_words = ["i", "it", "am", "is", "are", "be", "a", "an", "the", "as", "of", "at", "by", "to", "s", "t", "don", "https"]
    # Remove stop words
    words = [word for word in words if word not in stop_words]

    return words


def lemmatize_words(words: List[str]) -> List[str]:
    """
    Lemmatizes a list of words considering part of speech.

    Args:
        words (List[str]): List of words to lemmatize.

    Returns:
        List[str]: List of lemmatized words.
    """
    lemmatizer = WordNetLemmatizer()
    pos_tags = nltk.pos_tag(words)

    lemmatized_words = [
        lemmatizer.lemmatize(word, get_wordnet_pos(pos))
        for word, pos in pos_tags
    ]

    return lemmatized_words


def filter_english_words(words: List[str], english_vocab: Set[str]) -> List[str]:
    """
    Filters the list, keeping only English words.

    Args:
        words (List[str]): List of words.
        english_vocab (Set[str]): Set of English words.

    Returns:
        List[str]: List of English words.
    """

    return [word for word in words if word.lower() in english_vocab]


def process_text(text: str, english_vocab: Set[str], stop_words: Set[str],
                 brown_words: Set[str] = None) -> List[str]:
    """
    Processes text: tokenizes, filters, lemmatizes.

    Args:
        text (str): Source text.
        english_vocab (Set[str]): Set of English words.
        stop_words (Set[str]): Set of stop words.
        brown_words (Set[str]): Set of words from Brown corpus (for validating short words).

    Returns:
        List[str]: List of processed words.
    """
    # Tokenization and filtering
    words = tokenize_and_filter(text, stop_words)

    # Lemmatization
    lemmatized_words = lemmatize_words(words)

    # Filtering only English words
    english_words = filter_english_words(lemmatized_words, english_vocab)

    # Additional stop words (contractions are now expanded before tokenization)
    additional_stop_words = {"i", "it", "am", "is", "are", "be", "a", "an", "the", "as", "of", "at", "by", "to", "s", "t", "don"}

    # Fix common lemmatization errors (verb forms wrongly lemmatized)
    lemma_fixes = {
        "plat": "plate",  # plates wrongly lemmatized as verb
    }
    english_words = [lemma_fixes.get(word, word) for word in english_words]

    # Remove stop words
    # For short words (< 3 chars), keep only if they exist in Brown corpus
    def should_keep(word):
        if word in additional_stop_words:
            return False
        if len(word) < 3:
            # Keep short words only if they are in Brown corpus (real words like "on", "in", "go", "do")
            return brown_words is not None and word in brown_words
        return True

    english_words = [word for word in english_words if should_keep(word)]

    return english_words


def process_html_content(html_content: str, selector: str = None) -> List[str]:
    """
    Extracts and processes text from HTML content.

    Args:
        html_content (str): HTML content.
        selector (str, optional): CSS selector. Defaults to None.

    Returns:
        List[str]: List of processed words.
    """
    # Initialize NLTK resources
    english_vocab, _, stop_words = initialize_nltk()
    # Extract text
    text = extract_text_from_html(html_content, selector)

    # Process text
    return process_text(text, english_vocab, stop_words)


def prepare_word_data(words: List[str], brown_words: Set[str]) -> List[Tuple]:
    """
    Prepares word data for insertion into the database.

    Args:
        words (List[str]): List of words.
        brown_words (Set[str]): Set of words from the Brown corpus.

    Returns:
        List[Tuple]: List of tuples (word, listening_link, in_brown, frequency).
    """
    data = []
    word_counts = {}

    # Count word frequency
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1

    # Form data
    for word, frequency in word_counts.items():
        in_brown = word in brown_words
        listening_link = f"https://forvo.com/word/{word}/#en"
        data.append((word, listening_link, int(in_brown), frequency))

    return data
