#!/usr/bin/env python3
"""
Fix script for "Round the World in Eighty Days" book course.

Applies P0-P2 fixes to the exported JSON and saves a fixed version.

Usage:
    python scripts/fix_round_the_world_course.py            # Apply fixes and save
    python scripts/fix_round_the_world_course.py --dry-run   # Preview changes only
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = PROJECT_ROOT / "exports" / "round_the_world_course.json"
OUTPUT_PATH = PROJECT_ROOT / "exports" / "round_the_world_course_fixed.json"

GARBAGE_WORDS: set[str] = {"preform", "pall", "hong", "malabar", "bradshaw", "wilson"}

A1_BASIC_WORDS: set[str] = {
    "afternoon", "america", "american", "angry", "answer", "any", "anything",
    "arm", "arrive", "ate", "bad", "bag", "bank", "beautiful", "bed", "behind",
    "best", "big", "black", "blue", "boat", "book", "bring", "buy", "captain",
    "card", "carry", "city", "close", "clothes", "cold", "come", "country",
    "dark", "dead", "dinner", "door", "down", "drink", "drive", "early", "eat",
    "end", "evening", "eye", "face", "fall", "far", "fast", "fire", "five",
    "food", "foot", "friend", "front", "gave", "girl", "give", "gold", "good",
    "green", "ground", "half", "hand", "happy", "hard", "head", "hear", "help",
    "high", "hit", "home", "hope", "hot", "hour", "idea", "inside", "key",
    "kind", "king", "land", "large", "last", "late", "leave", "letter", "life",
    "light", "line", "listen", "live", "long", "look", "lose", "lot", "love",
    "man", "men", "met", "midnight", "money", "morning", "mouth", "much",
    "name", "near", "need", "next", "nice", "night", "nose", "number", "old",
    "open", "outside", "own", "paper", "park", "pay", "place", "play", "police",
    "poor", "pull", "put", "question", "quiet", "rain", "read", "red", "rest",
    "rich", "right", "ring", "river", "road", "room", "round", "run", "sad",
    "say", "sea", "sell", "send", "ship", "short", "show", "sit", "sky",
    "sleep", "small", "snow", "something", "son", "sorry", "south", "speak",
    "stand", "star", "start", "station", "stay", "stop", "stopped", "story",
    "street", "strong", "sun", "table", "talk", "tea", "tell", "think",
    "thousand", "together", "tomorrow", "top", "tree", "turn", "twenty",
    "understand", "wait", "walk", "wall", "want", "warm", "watch", "watched",
    "water", "way", "white", "wide", "win", "window", "winter", "woman",
    "wood", "word", "world", "write", "wrong", "year", "young",
    "november", "december", "october", "york", "san", "kong",
}

GRAMMAR_FOCUS: dict[int, list[str]] = {
    1: ["Present Simple for routines and habits",
        "Past Simple regular verbs (walked, waited, looked)"],
    2: ["Past Simple irregular verbs (went, came, got, took)",
        "Prepositions of movement (across, through, into)"],
    3: ["Modal verbs: can / cannot, have to",
        "Past Simple questions (Did he...? What did...?)"],
    4: ["Past Simple negative (didn't + verb)",
        "Prepositions of time (on Monday, at 3 o'clock, in the morning)"],
    5: ["Comparatives and superlatives (faster, the fastest)",
        "Basic conditionals: if + Present Simple"],
    6: ["Present Perfect for results (has won, has arrived)",
        "Time expressions (already, still, yet, ago)"],
}

VOCABULARY_FOCUS: dict[int, list[str]] = {
    1: ["servant", "club", "bet", "gentleman",
        "exactly", "strange", "passport", "journey", "wager", "punctual"],
    2: ["elephant", "temple", "guide", "jungle", "adventure", "rescue",
        "dangerous", "afraid", "immediately", "ceremony"],
    3: ["prison", "detective", "arrest", "escape", "passenger", "honest",
        "sailor", "weather", "storm", "harbour"],
    4: ["ticket", "platform", "crowd", "circus", "engine", "bridge",
        "attack", "delay", "passenger", "buffalo"],
    5: ["coal", "steam", "furniture", "voyage", "promise",
        "reward", "hurry", "aboard", "customs", "cargo"],
    6: ["calendar", "wedding", "discover", "mistake",
        "celebrate", "winner", "fortune", "happiness", "relief", "sincerely"],
}

MODULE_DESCRIPTIONS: dict[int, str] = {
    1: "Знакомство с Филеасом Фоггом и Паспарту. Повседневные привычки, характер героев.",
    2: "Начало путешествия. Пари в клубе, путь через Суэц и Индию.",
    3: "Спасение Ауды. Приключения в Калькутте и путь в Гонконг.",
    4: "Путешествие через Японию и Тихий океан. Приключения в Сан-Франциско.",
    5: "Путешествие через Америку. Поезда, задержки и Атлантический океан.",
    6: "Возвращение в Лондон. Развязка пари и счастливый финал.",
}

LITERARY_ELEMENTS: dict[int, list[str]] = {
    1: ["Character introduction through daily routine", "Setting: Victorian London"],
    2: ["Plot catalyst: the bet", "Journey narrative structure"],
    3: ["Heroic rescue as plot device", "Cultural contrast: East meets West"],
    4: ["Obstacles and problem-solving", "Comic relief through Passepartout"],
    5: ["Rising tension and time pressure", "Antagonist pursuit (Detective Fix)"],
    6: ["Plot twist and resolution", "Theme: friendship over money"],
}

ANNOTATION_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "vocabulary": {
        "objectives": [
            "Выучить новые слова из текста",
            "Запомнить перевод и произношение",
        ],
        "can_do": [
            "Могу перевести новые слова из главы",
            "Могу использовать слова в простых предложениях",
        ],
    },
    "language_focus": {
        "objectives": [
            "Разобрать грамматические конструкции из текста",
            "Потренировать грамматику в упражнениях",
        ],
        "can_do": [
            "Могу найти грамматическую конструкцию в тексте",
            "Могу составить похожее предложение",
        ],
    },
    "comprehension_mcq": {
        "objectives": [
            "Проверить понимание прочитанного текста",
            "Найти ключевую информацию в тексте",
        ],
        "can_do": [
            "Могу ответить на вопросы по тексту",
            "Могу найти конкретную информацию в тексте",
        ],
    },
    "phrase_cloze": {
        "objectives": [
            "Вспомнить ключевые слова и фразы из текста",
            "Потренировать правописание",
        ],
        "can_do": [
            "Могу вставить пропущенные слова в предложения",
            "Помню ключевые фразы из текста",
        ],
    },
    "context_review": {
        "objectives": [
            "Повторить выученные слова из предыдущих уроков",
            "Закрепить слова через интервальное повторение",
        ],
        "can_do": [
            "Могу вспомнить перевод слов из прошлых уроков",
            "Узнаю слова в новом контексте",
        ],
    },
    "guided_retelling": {
        "objectives": [
            "Пересказать содержание модуля своими словами",
            "Использовать выученную лексику в речи",
        ],
        "can_do": [
            "Могу рассказать основные события модуля",
            "Могу описать героев и их действия",
        ],
    },
    "module_test": {
        "objectives": [
            "Проверить знания по всему модулю",
            "Оценить прогресс в чтении и лексике",
        ],
        "can_do": [
            "Могу ответить на вопросы по всем главам модуля",
            "Знаю ключевые слова модуля",
        ],
    },
}

# Module IDs that need Day 1 vocabulary/reading swap (in the lessons array)
# Module 2 (id=40) and Module 5 (id=43) have reading before vocabulary on Day 1
MODULES_TO_SWAP_DAY1: set[int] = {40, 43}


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self) -> None:
        self.preform_fixes_slice_text: int = 0
        self.preform_fixes_context: int = 0
        self.preform_fixes_annotations: int = 0
        self.preform_fixes_task_payload: int = 0
        self.garbage_sv_removed: int = 0
        self.garbage_bv_removed: int = 0
        self.total_lessons_fixed: int = 0
        self.grammar_focus_set: int = 0
        self.vocabulary_focus_set: int = 0
        self.descriptions_set: int = 0
        self.literary_elements_set: int = 0
        self.a1_words_removed: int = 0
        self.day1_swaps: int = 0
        self.annotations_added: int = 0

    def print_summary(self) -> None:
        print("\n=== Fix Summary ===")
        print(f"  P0: 'Preform' -> 'Reform' in slice_text:      {self.preform_fixes_slice_text}")
        print(f"  P0: 'Preform' -> 'Reform' in context_sentence: {self.preform_fixes_context}")
        print(f"  P0: 'Preform' -> 'Reform' in annotations:      {self.preform_fixes_annotations}")
        print(f"  P0: 'Preform' -> 'Reform' in task payloads:    {self.preform_fixes_task_payload}")
        print(f"  P0: Garbage words removed (slice_vocab):        {self.garbage_sv_removed}")
        print(f"  P0: Garbage words removed (block_vocab):        {self.garbage_bv_removed}")
        print(f"  P0: total_lessons fixed:                        {self.total_lessons_fixed}")
        print(f"  P1: grammar_focus filled:                       {self.grammar_focus_set}")
        print(f"  P1: vocabulary_focus replaced:                  {self.vocabulary_focus_set}")
        print(f"  P1: A1 basic words removed (slice_vocab):       {self.a1_words_removed}")
        print(f"  P1: Day 1 vocab/reading swapped:                {self.day1_swaps}")
        print(f"  P1: Module descriptions replaced:               {self.descriptions_set}")
        print(f"  P2: literary_elements filled:                   {self.literary_elements_set}")
        print(f"  P2: Annotations added to practice lessons:      {self.annotations_added}")


# ---------------------------------------------------------------------------
# Fix functions
# ---------------------------------------------------------------------------

def fix_preform_in_text(data: dict[str, Any], stats: Stats) -> None:
    """P0: Fix 'Preform' -> 'Reform' in slice_text."""
    for lesson in data["lessons"]:
        if lesson["slice_text"] and "Preform" in lesson["slice_text"]:
            lesson["slice_text"] = lesson["slice_text"].replace("Preform", "Reform")
            stats.preform_fixes_slice_text += 1


def fix_preform_in_context_sentence(data: dict[str, Any], stats: Stats) -> None:
    """P0: Fix 'Preform' -> 'Reform' in context_sentence."""
    for sv in data["slice_vocabulary"]:
        if sv["context_sentence"] and "Preform" in sv["context_sentence"]:
            sv["context_sentence"] = sv["context_sentence"].replace("Preform", "Reform")
            stats.preform_fixes_context += 1


def fix_preform_in_annotations(data: dict[str, Any], stats: Stats) -> None:
    """P0: Fix 'Preform' -> 'Reform' in annotations (deep JSON)."""
    for lesson in data["lessons"]:
        if lesson["annotations"] is None:
            continue
        raw = json.dumps(lesson["annotations"])
        if "Preform" in raw:
            lesson["annotations"] = json.loads(raw.replace("Preform", "Reform"))
            stats.preform_fixes_annotations += 1


def fix_preform_in_task_payloads(data: dict[str, Any], stats: Stats) -> None:
    """P0: Fix 'Preform' -> 'Reform' in _task payloads embedded in lessons."""
    for lesson in data["lessons"]:
        task = lesson.get("_task")
        if task is None:
            continue
        raw = json.dumps(task, ensure_ascii=False)
        if "Preform" in raw:
            lesson["_task"] = json.loads(raw.replace("Preform", "Reform"))
            stats.preform_fixes_task_payload += 1


def remove_garbage_words(data: dict[str, Any], stats: Stats) -> None:
    """P0: Remove garbage C1/C2 words from slice_vocabulary and block_vocabulary."""
    orig_sv = len(data["slice_vocabulary"])
    data["slice_vocabulary"] = [
        sv for sv in data["slice_vocabulary"]
        if sv["_english_word"].lower() not in GARBAGE_WORDS
    ]
    stats.garbage_sv_removed = orig_sv - len(data["slice_vocabulary"])

    orig_bv = len(data["block_vocabulary"])
    data["block_vocabulary"] = [
        bv for bv in data["block_vocabulary"]
        if bv["_english_word"].lower() not in GARBAGE_WORDS
    ]
    stats.garbage_bv_removed = orig_bv - len(data["block_vocabulary"])


def fix_total_lessons(data: dict[str, Any], stats: Stats) -> None:
    """P0: Fix total_lessons to match actual lesson count."""
    for module in data["modules"]:
        ld = module["lessons_data"]
        actual = len(ld["lessons"])
        if ld["total_lessons"] != actual:
            ld["total_lessons"] = actual
            stats.total_lessons_fixed += 1


def fill_grammar_focus(data: dict[str, Any], stats: Stats) -> None:
    """P1: Fill grammar_focus for each module."""
    for module in data["modules"]:
        num = module["module_number"]
        if num in GRAMMAR_FOCUS:
            module["grammar_focus"] = GRAMMAR_FOCUS[num]
            stats.grammar_focus_set += 1


def replace_vocabulary_focus(data: dict[str, Any], stats: Stats) -> None:
    """P1: Replace weak vocabulary_focus with curated A2 words."""
    for module in data["modules"]:
        num = module["module_number"]
        if num in VOCABULARY_FOCUS:
            module["vocabulary_focus"] = VOCABULARY_FOCUS[num]
            stats.vocabulary_focus_set += 1


def remove_a1_basic_words(data: dict[str, Any], stats: Stats) -> None:
    """P1: Remove overly basic A1 words from slice_vocabulary."""
    orig = len(data["slice_vocabulary"])
    data["slice_vocabulary"] = [
        sv for sv in data["slice_vocabulary"]
        if sv["_english_word"].lower() not in A1_BASIC_WORDS
    ]
    stats.a1_words_removed = orig - len(data["slice_vocabulary"])


def fix_day1_lesson_order(data: dict[str, Any], stats: Stats) -> None:
    """P1: Ensure vocabulary comes before reading on Day 1 in the lessons array.

    For modules 2 and 5, the lessons array has reading before vocabulary.
    We swap lesson_type and related fields (word_count, annotations, audio_url)
    between the two Day 1 lessons.
    """
    for module_id in MODULES_TO_SWAP_DAY1:
        day1_lessons = [
            l for l in data["lessons"]
            if l["book_course_module_id"] == module_id and l["day_number"] == 1
        ]
        if len(day1_lessons) != 2:
            continue

        # Find reading and vocabulary lessons
        reading_lesson = None
        vocab_lesson = None
        for l in day1_lessons:
            if l["lesson_type"] == "reading":
                reading_lesson = l
            elif l["lesson_type"] == "vocabulary":
                vocab_lesson = l

        if not reading_lesson or not vocab_lesson:
            continue

        # Check if reading comes before vocabulary (by position in list)
        reading_idx = data["lessons"].index(reading_lesson)
        vocab_idx = data["lessons"].index(vocab_lesson)

        if reading_idx < vocab_idx:
            # Swap the lesson types and related fields
            swap_fields = ["lesson_type", "word_count", "annotations", "audio_url"]
            for field in swap_fields:
                reading_lesson[field], vocab_lesson[field] = (
                    vocab_lesson[field],
                    reading_lesson[field],
                )
            stats.day1_swaps += 1


def replace_module_descriptions(data: dict[str, Any], stats: Stats) -> None:
    """P1: Replace generic module descriptions."""
    for module in data["modules"]:
        num = module["module_number"]
        if num in MODULE_DESCRIPTIONS:
            module["description"] = MODULE_DESCRIPTIONS[num]
            stats.descriptions_set += 1


def fill_literary_elements(data: dict[str, Any], stats: Stats) -> None:
    """P2: Fill literary_elements for all modules."""
    for module in data["modules"]:
        num = module["module_number"]
        if num in LITERARY_ELEMENTS:
            module["literary_elements"] = LITERARY_ELEMENTS[num]
            stats.literary_elements_set += 1


def add_annotations_to_practice_lessons(data: dict[str, Any], stats: Stats) -> None:
    """P2: Add annotations to practice lessons that currently have none."""
    for lesson in data["lessons"]:
        if lesson["annotations"] is not None:
            continue
        lt = lesson["lesson_type"]
        if lt in ANNOTATION_TEMPLATES:
            # Deep copy to avoid shared mutable lists across lessons
            lesson["annotations"] = json.loads(json.dumps(ANNOTATION_TEMPLATES[lt]))
            stats.annotations_added += 1


# ---------------------------------------------------------------------------
# Post-fix statistics
# ---------------------------------------------------------------------------

def print_post_fix_stats(data: dict[str, Any]) -> None:
    """Print statistics about the fixed data."""
    print("\n=== Post-Fix Statistics ===")
    print(f"  Total modules: {len(data['modules'])}")
    print(f"  Total lessons: {len(data['lessons'])}")
    print(f"  Total slice_vocabulary: {len(data['slice_vocabulary'])}")
    print(f"  Total block_vocabulary: {len(data['block_vocabulary'])}")

    # Check no Preform remains
    preform_in_text = sum(
        1 for l in data["lessons"]
        if l["slice_text"] and "Preform" in l["slice_text"]
    )
    preform_in_ctx = sum(
        1 for sv in data["slice_vocabulary"]
        if sv["context_sentence"] and "Preform" in sv["context_sentence"]
    )
    print(f"  Remaining 'Preform' in slice_text: {preform_in_text}")
    print(f"  Remaining 'Preform' in context_sentence: {preform_in_ctx}")

    # Check task payloads
    preform_in_tasks = sum(
        1 for l in data["lessons"]
        if l.get("_task") and "Preform" in json.dumps(l["_task"], ensure_ascii=False)
    )
    print(f"  Remaining 'Preform' in task payloads: {preform_in_tasks}")

    # Check garbage words
    garbage_remaining = sum(
        1 for sv in data["slice_vocabulary"]
        if sv["_english_word"].lower() in GARBAGE_WORDS
    )
    print(f"  Remaining garbage words in slice_vocab: {garbage_remaining}")

    # Check total_lessons consistency
    mismatches = 0
    for m in data["modules"]:
        ld = m["lessons_data"]
        if ld["total_lessons"] != len(ld["lessons"]):
            mismatches += 1
    print(f"  total_lessons mismatches: {mismatches}")

    # Annotations coverage
    no_ann = sum(1 for l in data["lessons"] if l["annotations"] is None)
    print(f"  Lessons without annotations: {no_ann}")

    # Grammar/vocab focus
    empty_grammar = sum(1 for m in data["modules"] if not m["grammar_focus"])
    empty_literary = sum(1 for m in data["modules"] if not m["literary_elements"])
    print(f"  Modules with empty grammar_focus: {empty_grammar}")
    print(f"  Modules with empty literary_elements: {empty_literary}")

    # Day 1 order check
    for m in data["modules"]:
        mod_lessons = [
            l for l in data["lessons"]
            if l["book_course_module_id"] == m["id"] and l["day_number"] == 1
        ]
        types = [l["lesson_type"] for l in mod_lessons]
        if types and types[0] != "vocabulary":
            print(f"  WARNING: Module {m['module_number']} Day 1 starts with '{types[0]}' (expected 'vocabulary')")

    # A1 words remaining
    a1_remaining = sum(
        1 for sv in data["slice_vocabulary"]
        if sv["_english_word"].lower() in A1_BASIC_WORDS
    )
    print(f"  A1 basic words remaining in slice_vocab: {a1_remaining}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix Round the World in Eighty Days book course JSON"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes summary without saving",
    )
    args = parser.parse_args()

    if not INPUT_PATH.exists():
        print(f"ERROR: Input file not found: {INPUT_PATH}")
        sys.exit(1)

    print(f"Loading: {INPUT_PATH}")
    with open(INPUT_PATH, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    stats = Stats()

    # --- P0 fixes ---
    print("\nApplying P0 fixes (critical)...")
    fix_preform_in_text(data, stats)
    fix_preform_in_context_sentence(data, stats)
    fix_preform_in_annotations(data, stats)
    fix_preform_in_task_payloads(data, stats)
    remove_garbage_words(data, stats)
    fix_total_lessons(data, stats)

    # --- P1 fixes ---
    print("Applying P1 fixes (important)...")
    fill_grammar_focus(data, stats)
    replace_vocabulary_focus(data, stats)
    remove_a1_basic_words(data, stats)
    fix_day1_lesson_order(data, stats)
    replace_module_descriptions(data, stats)

    # --- P2 fixes ---
    print("Applying P2 fixes (improvements)...")
    fill_literary_elements(data, stats)
    add_annotations_to_practice_lessons(data, stats)

    # --- Summary ---
    stats.print_summary()
    print_post_fix_stats(data)

    if args.dry_run:
        print(f"\n[DRY RUN] No file written. Would save to: {OUTPUT_PATH}")
    else:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nSaved fixed course to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
