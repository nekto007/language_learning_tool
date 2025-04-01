"""
Setup and initialization of NLTK resources.
"""
import logging
import ssl

import nltk
from nltk.corpus import brown, stopwords, words as nltk_words

logger = logging.getLogger(__name__)

# Required NLTK resources
REQUIRED_RESOURCES = [
    "punkt",
    "stopwords",
    "averaged_perceptron_tagger",
    "wordnet",
    "words",
]


def setup_ssl_context():
    """
    Setup SSL context for downloading NLTK resources.
    Resolves certificate issues during download.
    """
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
        logger.info("SSL context set to unverified")
    except AttributeError:
        logger.warning("Could not modify SSL context")


def download_nltk_resources():
    """
    Downloads necessary NLTK resources.
    Checks for resource presence before downloading.
    """
    setup_ssl_context()

    for resource in REQUIRED_RESOURCES:
        try:
            try:
                nltk.data.find(f"tokenizers/{resource}")
                logger.info(f"Resource '{resource}' already downloaded")
            except LookupError:
                logger.info(f"Downloading NLTK resource: {resource}")
                nltk.download(resource, quiet=True)
        except Exception as e:
            logger.error(f"Failed to download '{resource}': {e}")


def get_english_vocabulary():
    """
    Returns a set of English words from NLTK.

    Returns:
        set: Set of English words in lowercase.
    """
    return set(w.lower() for w in nltk_words.words())


def get_brown_words():
    """
    Returns a set of words from the Brown corpus.

    Returns:
        set: Set of words from the Brown corpus.
    """
    return set(brown.words())


def get_stopwords():
    """
    Returns a set of stop words.

    Returns:
        set: Set of stop words.
    """
    return set(stopwords.words("english"))


def initialize_nltk():
    """
    Initializes all necessary NLTK resources.

    Returns:
        tuple: (english_vocab, brown_words, stop_words)
    """
    english_vocab = get_english_vocabulary()
    brown_words_set = get_brown_words()
    stop_words = get_stopwords()

    return english_vocab, brown_words_set, stop_words
