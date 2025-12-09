"""
Natural language processing module for English texts.
Includes functions for tokenization, lemmatization, and word processing.
"""
import logging
import re
from typing import List, Set, Tuple

import nltk
from bs4 import BeautifulSoup
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer

from app.nlp.setup import initialize_nltk

logger = logging.getLogger(__name__)

# Harry Potter specific names and made-up words to exclude
# These are proper nouns and fictional terms, not real English vocabulary
# Exported for use in other modules (daily_slice_generator, etc.)
HP_EXCLUSIONS = {
    # Character names (surnames and unusual first names only)
    "hermione", "granger", "weasley", "dumbledore", "voldemort", "snape",
    "hagrid", "lupin", "draco", "malfoy", "neville", "longbottom", "lovegood",
    "ginny", "tonks", "mcgonagall", "flitwick", "trelawney", "slughorn",
    "umbridge", "scrimgeour", "bellatrix", "lestrange", "lucius", "narcissa",
    "pettigrew", "wormtail", "padfoot", "prongs", "moony", "cho", "chang",
    "cedric", "diggory", "krum", "fleur", "delacour", "dobby", "kreacher",
    "winky", "hedwig", "crookshanks", "scabbers", "pigwidgeon", "errol",
    "fawkes", "nagini", "norbert", "norberta", "buckbeak", "aragog", "grawp",
    "firenze", "peeves", "filch", "pomfrey", "hooch", "quirrell", "lockhart",
    "riddle", "marvolo", "morfin", "merope", "gaunt", "gryffindor", "hufflepuff",
    "ravenclaw", "slytherin", "ollivander", "gregorovitch", "grindelwald",
    "flamel", "peverell", "dursley", "petunia", "mundungus", "aberforth",
    "ariana", "shunpike", "macmillan", "fletchley", "finnigan", "patil",
    "parkinson", "crabbe", "goyle", "zabini", "bulstrode", "spinnet",
    "mclaggen", "romilda", "creevey", "jorkins", "hepzibah", "hokey",
    "regulus", "arcturus", "walburga", "andromeda", "nymphadora", "fenrir",
    "greyback", "scabior", "yaxley", "rowle", "dolohov", "rookwood", "selwyn",
    "jugson", "mulciber", "rosier", "amycus", "alecto", "carrow", "rodolphus",
    "rabastan", "ignatius", "benjy", "fenwick", "mckinnon", "meadowes",
    "caradoc", "prewett", "emmeline", "podmore", "dedalus", "diggle",
    "elphias", "griselda", "marchbanks", "mafalda", "hopkirk", "broderick",
    "croaker", "peasegood", "inigo", "malkin", "fortescue", "florean",
    "celestina", "warbeck", "wagtail", "tremlett", "araminta", "meliflua",
    "phineas", "nigellus", "dippet", "derwent", "marjoribanks", "goshawk",
    "arsenius", "jigger", "bathilda", "bagshot", "waffling", "slinkhard",
    "vindictus", "viridian", "gilderoy",
    # First names that appear alone
    "harry", "ron", "dudley", "vernon", "arthur", "molly", "george", "fred",
    "percy", "charlie", "bill", "sirius", "remus", "albus", "severus",
    "minerva", "rubeus", "filius", "pomona", "sybill", "horace", "dolores",
    "cornelius", "rufus", "kingsley", "alastor", "mundungus", "nymphadora",
    "luna", "trevor", "ernie", "katie", "justin", "harold", "angelina",
    "lee", "dean", "seamus", "lavender", "parvati", "padma", "zacharias",
    "michael", "anthony", "terry", "mandy", "theodore", "blaise", "pansy",
    "millicent", "daphne", "marcus", "adrian", "graham", "montague",
    "james", "lily", "alicia", "fudge", "moody", "dung",
    # HP-specific place names
    "hogwarts", "hogsmeade", "diagon", "knockturn", "azkaban", "nurmengard",
    "durmstrang", "beauxbatons", "grimmauld", "gringotts", "ollivanders",
    "eeylops", "honeydukes", "zonko", "scrivenshaft", "gladrags", "puddifoot",
    "privet",
    # HP-specific magical terms (not real English words)
    "muggle", "muggles", "mudblood", "squib", "animagus", "animagi",
    "metamorphmagus", "legilimency", "legilimens", "occlumency", "occlumens",
    "horcrux", "horcruxes", "patronus", "patronuses", "dementor", "dementors",
    "inferius", "inferi", "thestral", "thestrals", "hippogriff", "hippogriffs",
    "acromantula", "acromantulas", "grindylow", "grindylows", "hinkypunk",
    "quintaped", "quintapeds", "billywig", "billywigs", "bowtruckle", "bowtruckles",
    "bundimun", "chizpurfle", "clabbert", "demiguise", "diricawl", "dugbog",
    "erkling", "erumpent", "flobberworm", "fwooper", "glumbumble", "graphorn",
    "hidebehind", "horklump", "jobberknoll", "knarl", "kneazle", "kneazles",
    "lobalug", "malaclaw", "mooncalf", "murtlap", "niffler", "nifflers",
    "nogtail", "occamy", "plimpy", "pogrebin", "porlock", "puffskein",
    "runespoor", "shrake", "snidget", "streeler", "tebo", "pukwudgie",
    "firebolt", "nimbus", "cleansweep", "bluebottle", "oakshaft", "moontrimmer",
    "tinderblast", "twigger", "swiftstick", "quaffle", "bludger", "snitch",
    "remembrall", "sneakoscope", "deluminator", "pensieve", "portkey",
    "timeturner", "erised", "triwizard", "apparate", "disapparate", "splinch",
    "prefect",  # HP-specific school term
    # HP spells (Latin-ish made-up words)
    "accio", "aguamenti", "alohomora", "anapneo", "aparecium", "avada",
    "kedavra", "bombarda", "brackium", "emendo", "colloportus", "confringo",
    "confundo", "crucio", "defodio", "deletrius", "densaugeo", "deprimo",
    "diffindo", "diminuendo", "dissendium", "engorgio", "episkey", "evanesco",
    "expelliarmus", "expulso", "ferula", "fidelius", "fiendfyre", "flagrate",
    "flipendo", "furnunculus", "geminio", "glisseo", "homenum", "revelio",
    "homonculous", "immobulus", "impedimenta", "imperio", "impervius",
    "incarcerous", "langlock", "levicorpus", "liberacorpus", "locomotor",
    "lumos", "meteolojinx", "mobiliarbus", "mobilicorpus", "morsmordre",
    "muffliato", "obliviate", "oppugno", "orchideous", "peskipiksi",
    "pesternomi", "petrificus", "totalus", "piertotum", "portus", "protego",
    "horribilis", "totalum", "reducio", "reducto", "relashio", "rennervate",
    "reparo", "repello", "muggletum", "rictusempra", "riddikulus", "salvio",
    "hexia", "scourgify", "sectumsempra", "serpensortia", "silencio", "sonorus",
    "spongify", "stupefy", "tarantallegra", "tergeo", "waddiwasi", "wingardium",
    "leviosa", "incantatem",
    # HP potions and made-up terms
    "amortentia", "polyjuice", "veritaserum", "wolfsbane", "pepperup",
    "bubotuber", "quidditch", "quibbler", "wizengamot", "auror", "aurors",
    "obliviator", "spew", "tentacula", "gillyweed", "mimbulus", "mimbletonia",
    "flitterbloom", "screechsnap", "snargaluff", "puffapod", "shrivelfig",
    "fluxweed", "knotgrass", "acanthia", "mungo",
    # HP-specific objects and terms
    "wand", "prophecy", "eater", "invisibility", "curse", "hex", "centaur",
    "serpent", "atrium", "yule", "bewitch", "potter",
}

# Hyphenated words that should be normalized to single words
# These are words where the hyphen is optional or archaic spelling
HYPHEN_NORMALIZATIONS = {
    "tri-pod": "tripod",
    "e-mail": "email",
    "co-operate": "cooperate",
    "co-operation": "cooperation",
    "co-ordinate": "coordinate",
    "co-ordination": "coordination",
    "re-enter": "reenter",
    "re-examine": "reexamine",
    "pre-eminent": "preeminent",
    "anti-aircraft": "antiaircraft",
    "non-sense": "nonsense",
    "to-day": "today",
    "to-morrow": "tomorrow",
    "to-night": "tonight",
    "any-one": "anyone",
    "every-one": "everyone",
    "some-one": "someone",
    "no-one": "noone",
    "any-thing": "anything",
    "every-thing": "everything",
    "some-thing": "something",
    "no-thing": "nothing",
    "any-where": "anywhere",
    "every-where": "everywhere",
    "some-where": "somewhere",
    "no-where": "nowhere",
    "mean-while": "meanwhile",
    "never-the-less": "nevertheless",
    "none-the-less": "nonetheless",
    "worth-while": "worthwhile",
    "fire-arm": "firearm",
    "fire-arms": "firearms",
    "air-plane": "airplane",
    "air-port": "airport",
    "bed-room": "bedroom",
    "bath-room": "bathroom",
    "living-room": "livingroom",
    "dining-room": "diningroom",
    "class-room": "classroom",
    "base-ball": "baseball",
    "basket-ball": "basketball",
    "foot-ball": "football",
    "news-paper": "newspaper",
    "sun-shine": "sunshine",
    "rain-bow": "rainbow",
    "tooth-brush": "toothbrush",
    "tooth-paste": "toothpaste",
    "lip-stick": "lipstick",
    "ear-ring": "earring",
    "ear-rings": "earrings",
    "hand-bag": "handbag",
    "suit-case": "suitcase",
    "back-pack": "backpack",
    "lap-top": "laptop",
    "key-board": "keyboard",
    "pass-word": "password",
    "user-name": "username",
    "web-site": "website",
    "on-line": "online",
    "off-line": "offline",
    "down-load": "download",
    "up-load": "upload",
    "log-in": "login",
    "log-out": "logout",
    "sign-in": "signin",
    "sign-up": "signup",
    "check-out": "checkout",
    "break-fast": "breakfast",
    "week-end": "weekend",
    "birth-day": "birthday",
    "boy-friend": "boyfriend",
    "girl-friend": "girlfriend",
    "grand-mother": "grandmother",
    "grand-father": "grandfather",
    "grand-parent": "grandparent",
    "grand-parents": "grandparents",
    "grand-child": "grandchild",
    "grand-children": "grandchildren",
    "step-mother": "stepmother",
    "step-father": "stepfather",
    "step-sister": "stepsister",
    "step-brother": "stepbrother",
    "half-sister": "halfsister",
    "half-brother": "halfbrother",
    "every-body": "everybody",
    "some-body": "somebody",
    "any-body": "anybody",
    "no-body": "nobody",
    "can-not": "cannot",
    "in-side": "inside",
    "out-side": "outside",
    "up-stairs": "upstairs",
    "down-stairs": "downstairs",
    "over-night": "overnight",
    "under-ground": "underground",
    "with-out": "without",
    "with-in": "within",
    "al-ready": "already",
    "al-ways": "always",
    "al-most": "almost",
    "al-so": "also",
    "al-though": "although",
    "al-together": "altogether",
    "my-self": "myself",
    "your-self": "yourself",
    "him-self": "himself",
    "her-self": "herself",
    "it-self": "itself",
    "our-selves": "ourselves",
    "them-selves": "themselves",
    "every-day": "everyday",
    "some-times": "sometimes",
    "any-time": "anytime",
    "mean-time": "meantime",
    "life-time": "lifetime",
    "day-time": "daytime",
    "night-time": "nighttime",
    "bed-time": "bedtime",
    "break-down": "breakdown",
    "break-through": "breakthrough",
    "make-up": "makeup",
    "set-up": "setup",
    "work-out": "workout",
    "hand-out": "handout",
    "out-come": "outcome",
    "out-put": "output",
    "in-put": "input",
    "out-break": "outbreak",
    "out-fit": "outfit",
    "out-line": "outline",
    "out-look": "outlook",
    "over-all": "overall",
    "over-come": "overcome",
    "over-look": "overlook",
    "over-take": "overtake",
    "over-time": "overtime",
    "over-weight": "overweight",
    "under-stand": "understand",
    "under-take": "undertake",
    "under-wear": "underwear",
    "up-date": "update",
    "up-grade": "upgrade",
    "up-set": "upset",
    "back-ground": "background",
    "fore-ground": "foreground",
    "play-ground": "playground",
    "home-work": "homework",
    "house-work": "housework",
    "team-work": "teamwork",
    "net-work": "network",
    "frame-work": "framework",
    "fire-work": "firework",
    "fire-works": "fireworks",
    "book-mark": "bookmark",
    "land-mark": "landmark",
    "trade-mark": "trademark",
    "post-card": "postcard",
    "credit-card": "creditcard",
    "cup-board": "cupboard",
    "card-board": "cardboard",
    "key-board": "keyboard",
    "black-board": "blackboard",
    "skate-board": "skateboard",
    "snow-board": "snowboard",
    "surf-board": "surfboard",
    "dash-board": "dashboard",
    "clip-board": "clipboard",
    "head-ache": "headache",
    "stomach-ache": "stomachache",
    "tooth-ache": "toothache",
    "back-ache": "backache",
    "heart-beat": "heartbeat",
    "heart-break": "heartbreak",
    "sun-set": "sunset",
    "sun-rise": "sunrise",
    "moon-light": "moonlight",
    "sun-light": "sunlight",
    "day-light": "daylight",
    "flash-light": "flashlight",
    "head-light": "headlight",
    "spot-light": "spotlight",
    "high-light": "highlight",
    "lime-light": "limelight",
    "candle-light": "candlelight",
    "star-light": "starlight",
    "fire-place": "fireplace",
    "work-place": "workplace",
    "market-place": "marketplace",
    "birth-place": "birthplace",
    "common-place": "commonplace",
    "hiding-place": "hidingplace",
    "land-scape": "landscape",
    "sea-scape": "seascape",
    "city-scape": "cityscape",
    "sound-scape": "soundscape",
    "dream-scape": "dreamscape",
    "sky-scraper": "skyscraper",
    "eye-brow": "eyebrow",
    "eye-lash": "eyelash",
    "eye-lid": "eyelid",
    "eye-sight": "eyesight",
    "eye-witness": "eyewitness",
    "fore-head": "forehead",
    "arm-chair": "armchair",
    "wheel-chair": "wheelchair",
    "high-chair": "highchair",
    "hair-cut": "haircut",
    "short-cut": "shortcut",
    "hair-style": "hairstyle",
    "life-style": "lifestyle",
    "free-style": "freestyle",
    "book-case": "bookcase",
    "stair-case": "staircase",
    "brief-case": "briefcase",
    "show-case": "showcase",
    "lower-case": "lowercase",
    "upper-case": "uppercase",
    "court-yard": "courtyard",
    "back-yard": "backyard",
    "church-yard": "churchyard",
    "grave-yard": "graveyard",
    "vine-yard": "vineyard",
    "ship-yard": "shipyard",
    "junk-yard": "junkyard",
    "school-yard": "schoolyard",
    "barn-yard": "barnyard",
    "stock-yard": "stockyard",
}


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
        # Informal/dialectal contractions (e.g., "'gree" -> "agree")
        "'gree": "agree",
        "'bout": "about",
        "'cause": "because",
        "'em": "them",
        "'til": "until",
        "'tis": "it is",
        "'twas": "it was",
        "'ere": "here",
        "'dere": "there",
        "'ouse": "house",
        "'arry": "harry",
        # Dropped g in -ing words (savin' -> saving)
        "in'": "ing",
        # Cockney/dialect pronunciations (Hagrid, Mundungus)
        "orf": "off",
        "nuffink": "nothing",
        "summat": "something",
        "wiv": "with",
        "fer": "for",
        "ter": "to",
        "yeh": "you",
        "yer": "your",
        "bin": "been",
        "wuz": "was",
        "meself": "myself",
        "yerself": "yourself",
        # More dialect words
        "ave": "have",
        "bes": "best",
        "kep": "kept",
        "gon": "going",
        "myst": "must",
        "pur": "pure",
        "roun": "round",
        "mon": "man",
        "wha": "what",
        "tha": "that",
        "wid": "with",
        "de": "the",
        "la": "the",
        "en": "and",
        "fraid": "afraid",
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

    # Replace em-dashes, en-dashes and other special dashes with spaces
    # so words like "these—ouch—shoes" are properly tokenized
    text = re.sub(r'[—–−‐‑‒―]', ' ', text)

    # Normalize hyphenated words that should be single words
    # e.g., "tri-pod" -> "tripod", "e-mail" -> "email"
    for hyphenated, normalized in HYPHEN_NORMALIZATIONS.items():
        text = re.sub(r'\b' + re.escape(hyphenated) + r'\b', normalized, text, flags=re.IGNORECASE)

    # Replace hyphens with spaces to split compound words
    # like "triple-decker" into "triple" and "decker"
    text = text.replace('-', ' ')

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

    # Remove stop words and HP-specific terms
    # For short words (< 3 chars), keep only if they exist in Brown corpus
    def should_keep(word):
        if word in additional_stop_words:
            return False
        if word in HP_EXCLUSIONS:
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
