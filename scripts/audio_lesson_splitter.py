#!/usr/bin/env python3
"""
Audio Lesson Splitter

Splits audiobook into segments matching lesson texts using forced alignment.
Uses Whisper for transcription with word-level timestamps, then matches
lesson text to find exact audio segments.

Usage:
    python scripts/audio_lesson_splitter.py --m4b "path/to/audiobook.m4b" --course-id 14

Requirements:
    pip install openai-whisper stable-ts
"""
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class ChapterInfo:
    """Audiobook chapter metadata"""
    index: int
    title: str
    start_time: float
    end_time: float


@dataclass
class LessonSegment:
    """Lesson audio segment info"""
    lesson_id: int
    day_number: int
    slice_number: int
    chapter_id: int
    text: str
    start_time: float
    end_time: float
    audio_path: Optional[str] = None


def generate_audio_filename(course_id: int, chapter_num: int, sequential_number: int) -> str:
    """
    Generate audio filename using new naming scheme.

    Format: course_{course_id}_ch{chapter_num}_lesson{seq}.mp3

    Examples:
        course_17_ch1_lesson1.mp3
        course_17_ch4_lesson10.mp3
        course_17_ch17_lesson105.mp3
    """
    return f"course_{course_id}_ch{chapter_num}_lesson{sequential_number}.mp3"


class AudioLessonSplitter:
    """Main class for splitting audiobook into lesson segments"""

    def __init__(self, m4b_path: str, output_dir: str, ffmpeg_path: str = "./ffmpeg", precision: str = "medium", interactive: bool = False, transcripts_dir: str = None):
        self.m4b_path = Path(m4b_path)
        self.output_dir = Path(output_dir)
        # Convert to absolute path if relative
        ffmpeg_p = Path(ffmpeg_path)
        if not ffmpeg_p.is_absolute():
            ffmpeg_p = Path.cwd() / ffmpeg_p
        self.ffmpeg_path = str(ffmpeg_p.absolute())
        self.chapters_dir = self.output_dir / "chapters"
        self.lessons_dir = self.output_dir / "lessons"
        # Allow custom transcripts directory
        if transcripts_dir:
            self.transcripts_dir = Path(transcripts_dir)
        else:
            self.transcripts_dir = self.output_dir / "transcripts"

        # Set matching thresholds based on precision
        # Lowered thresholds to handle Whisper transcription errors
        # With errors like "Dudley jerked awake" → "sadly j rg to rake",
        # we need more lenient matching (50-word window gives ~70% even with errors)
        self.precision = precision
        self.match_thresholds = {
            "low": 0.50,     # Was 0.6 - allow 50% match for heavy errors
            "medium": 0.60,  # Was 0.7 - 60% match is reasonable with errors
            "high": 0.70     # Was 0.8 - 70% for clean transcripts
        }
        self.match_threshold = self.match_thresholds.get(precision, 0.6)
        self.interactive = interactive

        # Create directories
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        self.lessons_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    def get_chapters_from_m4b(self) -> List[ChapterInfo]:
        """Extract chapter information from M4B file"""
        cmd = [
            self.ffmpeg_path, "-i", str(self.m4b_path),
            "-f", "ffmetadata", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Parse ffmpeg output for chapters
        chapters = []
        output = result.stderr  # ffmpeg outputs to stderr

        # Pattern: Chapter #0:N: start X.XXX, end Y.YYY
        chapter_pattern = r"Chapter #0:(\d+): start ([\d.]+), end ([\d.]+)"
        title_pattern = r"title\s*:\s*(.+)"

        lines = output.split('\n')
        current_chapter = None

        for i, line in enumerate(lines):
            chapter_match = re.search(chapter_pattern, line)
            if chapter_match:
                idx = int(chapter_match.group(1))
                start = float(chapter_match.group(2))
                end = float(chapter_match.group(3))
                current_chapter = ChapterInfo(
                    index=idx,
                    title=f"Chapter {idx}",
                    start_time=start,
                    end_time=end
                )
                # Look for title in next few lines
                for j in range(i + 1, min(i + 5, len(lines))):
                    title_match = re.search(title_pattern, lines[j])
                    if title_match:
                        current_chapter.title = title_match.group(1).strip()
                        break
                chapters.append(current_chapter)

        return chapters

    def extract_chapter_audio(self, chapter: ChapterInfo, output_format: str = "mp3") -> Path:
        """Extract a single chapter from M4B as separate audio file"""
        output_path = self.chapters_dir / f"chapter_{chapter.index:02d}.{output_format}"

        if output_path.exists():
            print(f"  Chapter {chapter.index} already extracted, skipping...")
            return output_path

        duration = chapter.end_time - chapter.start_time

        cmd = [
            self.ffmpeg_path,
            "-i", str(self.m4b_path),
            "-ss", str(chapter.start_time),
            "-t", str(duration),
            "-acodec", "libmp3lame" if output_format == "mp3" else "aac",
            "-q:a", "0",  # Maximum quality (320kbps for better Whisper transcription)
            "-y",  # Overwrite
            str(output_path)
        ]

        print(f"  Extracting chapter {chapter.index}: {chapter.title} ({duration:.1f}s)")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"  Error extracting chapter: {result.stderr[:200]}")
            return None

        return output_path

    def transcribe_chapter(self, chapter_path: Path, chapter_index: int) -> dict:
        """Transcribe chapter using stable-ts with word timestamps"""
        transcript_path = self.transcripts_dir / f"chapter_{chapter_index:02d}.json"

        if transcript_path.exists():
            print(f"  Transcript for chapter {chapter_index} exists, loading...")
            with open(transcript_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        print(f"  Transcribing chapter {chapter_index}...")

        try:
            import stable_whisper

            # Load model (use 'base' for speed, 'large' for accuracy)
            model = stable_whisper.load_model("base")

            # Transcribe with word timestamps
            result = model.transcribe(
                str(chapter_path),
                word_timestamps=True,
                language="en"
            )

            # Convert to serializable format
            transcript = {
                "text": result.text,
                "segments": []
            }

            for segment in result.segments:
                seg_data = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": []
                }
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        seg_data["words"].append({
                            "word": word.word,
                            "start": word.start,
                            "end": word.end
                        })
                transcript["segments"].append(seg_data)

            # Save transcript
            with open(transcript_path, 'w', encoding='utf-8') as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)

            return transcript

        except ImportError:
            print("  stable-ts not installed, trying regular whisper...")
            import whisper

            model = whisper.load_model("base")
            result = model.transcribe(str(chapter_path), word_timestamps=True, language="en")

            transcript = {
                "text": result["text"],
                "segments": result["segments"]
            }

            with open(transcript_path, 'w', encoding='utf-8') as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)

            return transcript

    def normalize_text(self, text: str) -> str:
        """Normalize text for comparison"""
        text = text.lower()
        # Remove punctuation except apostrophes
        text = re.sub(r"[^\w\s']", " ", text)
        # Normalize whitespace
        text = " ".join(text.split())

        # Fix split contractions (common in book text vs audiobook)
        # "they ve" -> "they've", "it s" -> "it's", "don t" -> "don't", etc.
        contractions = {
            r'\b(\w+)\s+ve\b': r"\1've",     # they ve -> they've
            r'\b(\w+)\s+ll\b': r"\1'll",     # i ll -> i'll
            r'\b(\w+)\s+re\b': r"\1're",     # you re -> you're
            r'\b(\w+)\s+d\b': r"\1'd",       # he d -> he'd
            r'\b(\w+)\s+s\b': r"\1's",       # it s -> it's
            r'\b(\w+)\s+t\b': r"\1't",       # don t -> don't, can t -> can't
            r'\b(\w+)\s+m\b': r"\1'm",       # i m -> i'm
        }

        for pattern, replacement in contractions.items():
            text = re.sub(pattern, replacement, text)

        return text

    def find_text_with_adaptive_precision(
        self,
        lesson_text: str,
        transcript: dict,
        lesson_id: Optional[int] = None
    ) -> Tuple[Optional[float], Optional[float], str]:
        """
        Try to find text with progressively relaxed precision levels.
        Returns (start_time, end_time, precision_used)
        """
        # Define precision levels to try in order
        precision_levels = ["high", "medium", "low"]

        # Start from the requested precision level
        start_idx = precision_levels.index(self.precision) if self.precision in precision_levels else 1

        # Enable debug for specific lesson
        debug_lesson_id = lesson_id if lesson_id == 6576 else None

        for precision in precision_levels[start_idx:]:
            # Temporarily set the threshold for this precision
            original_threshold = self.match_threshold
            self.match_threshold = self.match_thresholds[precision]

            if debug_lesson_id:
                print(f"      Trying {precision} precision (threshold={self.match_threshold})...")

            # Try to find text
            start_time, end_time = self.find_text_in_transcript(
                lesson_text,
                transcript,
                debug_lesson_id=debug_lesson_id
            )

            # Restore original threshold
            self.match_threshold = original_threshold

            if start_time is not None and end_time is not None:
                return start_time, end_time, precision

        # No match found at any precision level
        if debug_lesson_id:
            print(f"      [DEBUG] No match found at any precision level!")
        return None, None, "none"

    def find_text_in_transcript(
        self,
        lesson_text: str,
        transcript: dict,
        search_window: int = 50,
        debug_lesson_id: Optional[int] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Find lesson text in transcript and return start/end times.
        Uses fuzzy matching to handle transcription errors.

        NEW: If beginning of lesson is not found (narrator skipped dialogue),
        tries to find match from different starting positions in the lesson text.
        """
        normalized_lesson = self.normalize_text(lesson_text)
        lesson_words = normalized_lesson.split()

        if not lesson_words:
            return None, None

        is_debug = debug_lesson_id is not None

        # Get all words with timestamps from transcript
        all_words = []
        for segment in transcript.get("segments", []):
            for word_info in segment.get("words", []):
                all_words.append({
                    "word": self.normalize_text(word_info.get("word", "")),
                    "start": word_info.get("start", 0),
                    "end": word_info.get("end", 0)
                })

        if not all_words:
            # Fallback: use segment-level timestamps
            print("    No word-level timestamps, using segment matching...")
            return self._find_text_in_segments(lesson_text, transcript)

        # Try to find match starting from different positions in lesson text
        # Position 0 = normal (start from beginning)
        # Position 5, 10, 15... = fallback if narrator skipped beginning dialogue
        positions_to_try = [0]

        # If lesson is long enough, try every 5 words up to position 50
        # Changed from 10 to 5 to catch more skip patterns (e.g., 17 words)
        if len(lesson_words) > 60:
            positions_to_try.extend(range(5, min(50, len(lesson_words) - 50), 5))

        for skip_words in positions_to_try:
            if skip_words > 0:
                print(f"      Trying to match from position +{skip_words} words (skipping beginning)...")

            # Adjust lesson words based on skip position
            adjusted_lesson_words = lesson_words[skip_words:]

            # Define search windows
            # For very short lessons (<30 words), use smaller window
            # For short lessons (30-60 words), use 60% of lesson length
            # For normal lessons (>60 words), use 50 words
            if len(adjusted_lesson_words) < 30:
                # Very short lesson - use entire lesson as window
                window_size = len(adjusted_lesson_words)
            elif len(adjusted_lesson_words) < 60:
                # Short lesson - use 60% of lesson
                window_size = max(10, int(len(adjusted_lesson_words) * 0.6))
            else:
                # Normal lesson - use 50 words
                window_size = 50

            first_words = adjusted_lesson_words[:min(window_size, len(adjusted_lesson_words))]
            last_words = adjusted_lesson_words[-min(window_size, len(adjusted_lesson_words)):]

            if is_debug and skip_words == 0:
                print(f"\n      [DEBUG LESSON {debug_lesson_id}]")
                print(f"      Lesson text length: {len(lesson_text)} chars, {len(lesson_words)} words")
                print(f"      Search window: {len(first_words)} words (increased from 10 to handle Whisper errors)")
                print(f"      First 10 words: {' '.join(lesson_words[:10])}")
                print(f"      Last 10 words: {' '.join(lesson_words[-10:])}")
                print(f"      Match threshold: {self.match_threshold} ({self.match_threshold*100:.0f}%), need {int(len(first_words) * self.match_threshold)}/{len(first_words)} matching words")

            # Find best match using sliding window
            best_match_start = None
            best_match_end = None
            best_score = 0

            if is_debug and skip_words == 0:
                print(f"      Searching in {len(all_words)} transcript words...")
                print(f"      Looking for first words: {' '.join(first_words)}")

            match_attempts = 0
            for i in range(len(all_words) - len(first_words)):
                # Check if first words match
                window_words = [w["word"] for w in all_words[i:i + len(first_words)]]
                score = sum(1 for a, b in zip(first_words, window_words) if a == b)

                if is_debug and score >= len(first_words) * 0.6:  # Show attempts with >60% match
                    match_attempts += 1
                    if match_attempts <= 5:  # Show first 5 attempts
                        print(f"      Attempt at pos {i}: score={score}/{len(first_words)} ({score/len(first_words)*100:.0f}%), window: {' '.join(window_words[:10])}...")

                if score > best_score and score >= len(first_words) * self.match_threshold:
                    best_score = score
                    best_match_start = all_words[i]["start"]

                    # Now find the end
                    # Use tighter estimation: +5 words instead of +20
                    estimated_end_idx = min(i + len(adjusted_lesson_words) + 5, len(all_words) - 1)

                    # Try exact match first for better precision
                    last_words_exact = last_words
                    exact_match_found = False

                    for j in range(estimated_end_idx, max(i + len(adjusted_lesson_words) - 5, i), -1):
                        window = all_words[max(0, j-len(last_words_exact)+1):j+1]
                        window_texts = [w["word"] for w in window]

                        # Check for exact match
                        if len(window_texts) == len(last_words_exact) and window_texts == last_words_exact:
                            best_match_end = all_words[j]["end"]
                            exact_match_found = True
                            break

                    # If no exact match, fall back to fuzzy matching with narrower window
                    if not exact_match_found:
                        # Narrow search window to ±5 words around estimated position
                        search_start = estimated_end_idx
                        search_end = max(i + len(adjusted_lesson_words) - 5, i)
                        for j in range(search_start, search_end, -1):
                            end_window = [w["word"] for w in all_words[max(0, j - len(last_words)):j]]
                            end_score = sum(1 for a, b in zip(last_words, end_window) if a == b)
                            if end_score >= len(last_words) * self.match_threshold:
                                best_match_end = all_words[min(j, len(all_words) - 1)]["end"]
                                break

                    if best_match_end is None:
                        # Estimate end time based on word count
                        end_idx = min(i + len(adjusted_lesson_words), len(all_words) - 1)
                        best_match_end = all_words[end_idx]["end"]

            # If we found a match at this position, use it
            if best_match_start is not None and best_match_end is not None:
                if skip_words > 0:
                    print(f"      ✅ Found match starting from position +{skip_words} words!")
                    print(f"      ⚠️  WARNING: First {skip_words} words of lesson were skipped by narrator")
                break

        # If still no match found after trying all positions
        if best_match_start is None or best_match_end is None:
            return None, None

        # Validate matched segment length (use adjusted lesson words if we skipped beginning)
        if best_match_start and best_match_end:
            # Calculate expected length based on what we actually matched
            adjusted_normalized_lesson = " ".join(adjusted_lesson_words)
            lesson_char_count = len(adjusted_normalized_lesson)

            # Find matching words in transcript
            matched_words = []
            for w in all_words:
                if best_match_start <= w["start"] <= best_match_end:
                    matched_words.append(w["word"])

            matched_char_count = sum(len(w) for w in matched_words) + len(matched_words) - 1  # +spaces

            # DEBUG: Always print validation info
            if skip_words > 0:
                print(f"      [DEBUG] Skipped {skip_words} words from lesson start")
            print(f"      [DEBUG] Lesson chars: {lesson_char_count}, Matched chars: {matched_char_count}, Matched words: {len(matched_words)}")

            # Allow only 2% variance for very tight matching
            lower_bound = lesson_char_count * 0.98
            upper_bound = lesson_char_count * 1.02

            if not (lower_bound <= matched_char_count <= upper_bound):
                print(f"      ⚠️  Length mismatch: lesson={lesson_char_count}, matched={matched_char_count} (bounds: {lower_bound:.0f}-{upper_bound:.0f})")
                # Try to adjust boundaries if segment is too long
                if matched_char_count > upper_bound:
                    target_char_count = lesson_char_count
                    cumulative_chars = 0
                    adjusted_end = best_match_start

                    for w in all_words:
                        if w["start"] < best_match_start:
                            continue
                        cumulative_chars += len(w["word"]) + 1
                        if cumulative_chars >= target_char_count:
                            adjusted_end = w["end"]
                            break

                    if adjusted_end > best_match_start:
                        print(f"      ✓ Adjusted end: {best_match_end:.1f}s → {adjusted_end:.1f}s")
                        best_match_end = adjusted_end

            # Log matching statistics (use adjusted lesson words for duration estimate)
            duration = best_match_end - best_match_start
            lesson_word_count = len(adjusted_lesson_words)

            # Estimate expected duration (average 2.5 words/second in audiobooks)
            expected_duration = lesson_word_count / 2.5
            duration_diff = abs(duration - expected_duration)

            # DEBUG: Always print duration info
            print(f"      [DEBUG] Expected duration: {expected_duration:.1f}s, Actual: {duration:.1f}s, Diff: {duration_diff:.1f}s ({duration_diff/expected_duration*100:.1f}%)")

            if duration_diff > expected_duration * 0.1:  # >10% difference
                print(f"      ⚠️  Duration mismatch: expected ~{expected_duration:.1f}s, got {duration:.1f}s ({duration_diff/expected_duration*100:.1f}% diff)")

        if is_debug:
            if best_match_start and best_match_end:
                print(f"      [DEBUG] MATCH FOUND: {best_match_start:.1f}s - {best_match_end:.1f}s (score={best_score})")
            else:
                print(f"      [DEBUG] NO MATCH (best_score={best_score}, needed={len(first_words) * self.match_threshold:.1f})")

        return best_match_start, best_match_end

    def _find_text_in_segments(
        self,
        lesson_text: str,
        transcript: dict
    ) -> Tuple[Optional[float], Optional[float]]:
        """Fallback: find text using segment-level matching"""
        normalized_lesson = self.normalize_text(lesson_text)

        # Concatenate all segment texts
        full_text = ""
        segment_positions = []  # (start_char, end_char, start_time, end_time)

        for segment in transcript.get("segments", []):
            seg_text = self.normalize_text(segment.get("text", ""))
            start_pos = len(full_text)
            full_text += seg_text + " "
            segment_positions.append((
                start_pos,
                len(full_text),
                segment.get("start", 0),
                segment.get("end", 0)
            ))

        # Find lesson text in full transcript
        # Use first 100 chars for matching
        search_text = normalized_lesson[:100]
        pos = full_text.find(search_text)

        if pos == -1:
            # Try with first 50 chars
            search_text = normalized_lesson[:50]
            pos = full_text.find(search_text)

        if pos == -1:
            return None, None

        end_pos = pos + len(normalized_lesson)

        # Find corresponding segments
        start_time = None
        end_time = None

        for start_char, end_char, seg_start, seg_end in segment_positions:
            if start_char <= pos < end_char and start_time is None:
                # Interpolate start time within segment
                ratio = (pos - start_char) / max(1, end_char - start_char)
                start_time = seg_start + ratio * (seg_end - seg_start)

            if start_char <= end_pos <= end_char:
                ratio = (end_pos - start_char) / max(1, end_char - start_char)
                end_time = seg_start + ratio * (seg_end - seg_start)
                break
            elif end_pos < start_char:
                break
            else:
                end_time = seg_end

        return start_time, end_time

    def extract_lesson_audio(
        self,
        chapter_path: Path,
        lesson: LessonSegment,
        course_id: int,
        chapter_num: int,
        sequential_number: int,
        chapter_offset: float = 0
    ) -> Optional[Path]:
        """Extract lesson audio segment from chapter"""
        # NEW: Use stable filename instead of database ID
        filename = generate_audio_filename(course_id, chapter_num, sequential_number)
        output_path = self.lessons_dir / filename

        if output_path.exists():
            print(f"    Lesson {lesson.lesson_id} already extracted")
            return output_path

        # Adjust times for chapter offset
        start = lesson.start_time
        end = lesson.end_time
        duration = end - start

        if duration <= 0:
            print(f"    Invalid duration for lesson {lesson.lesson_id}")
            return None

        # Add small padding
        start = max(0, start - 0.5)
        duration += 1.0

        cmd = [
            self.ffmpeg_path,
            "-i", str(chapter_path),
            "-ss", str(start),
            "-t", str(duration),
            "-acodec", "libmp3lame",
            "-q:a", "2",
            "-y",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"    Error: {result.stderr[:100]}")
            return None

        # Update database with audio_url
        from app import db
        from app.curriculum.daily_lessons import DailyLesson

        lesson_obj = DailyLesson.query.get(lesson.lesson_id)
        if lesson_obj:
            # Store relative path for Flask static files
            # Path is relative to app/static/ folder
            relative_path = f"audio/lessons/{filename}"
            lesson_obj.audio_url = relative_path
            db.session.commit()
            print(f"      ✅ Updated audio_url: {relative_path}")

        return output_path

    def process_course(self, course_id: int, lesson_id: Optional[int] = None):
        """Process all lessons for a course (or specific lesson if lesson_id provided)"""
        from app import create_app
        app = create_app()

        with app.app_context():
            from app.curriculum.book_courses import BookCourse, BookCourseModule
            from app.curriculum.daily_lessons import DailyLesson
            from app.books.models import Chapter

            course = BookCourse.query.get(course_id)
            if not course:
                print(f"Course {course_id} not found")
                return

            print(f"\n{'='*60}")
            if lesson_id:
                print(f"Processing: {course.title} - Lesson {lesson_id} only")
            else:
                print(f"Processing: {course.title}")
            print(f"{'='*60}")

            # Get chapters from M4B
            print("\n1. Extracting chapter info from M4B...")
            chapters = self.get_chapters_from_m4b()
            print(f"   Found {len(chapters)} chapters")

            # Map chapter titles to indices
            # Skip "Opening Credits" and similar
            book_chapters = [c for c in chapters if "Chapter" in c.title]
            print(f"   Book chapters: {len(book_chapters)}")

            # Extract all chapters first
            print("\n2. Extracting chapter audio files...")
            chapter_paths = {}
            for chapter in book_chapters:
                path = self.extract_chapter_audio(chapter)
                if path:
                    chapter_paths[chapter.index] = {
                        "path": path,
                        "info": chapter
                    }

            # Get all reading lessons from course
            print("\n3. Getting lesson data from database...")
            modules = BookCourseModule.query.filter_by(course_id=course_id).all()

            lessons_to_process = []
            for module in modules:
                print(f"   Processing {module.title}")
                daily_lessons = DailyLesson.query.filter_by(
                    book_course_module_id=module.id,
                    lesson_type='reading'  # Only reading lessons need audio
                ).all()

                for dl in daily_lessons:
                    # print(f"   Processing {dl.book_course_module_id}")
                    if dl.slice_text and dl.chapter_id:
                        # Get real chapter number from Chapter table
                        chapter = Chapter.query.get(dl.chapter_id)
                        if chapter:
                            lessons_to_process.append({
                                "lesson_id": dl.id,
                                "day_number": dl.day_number,
                                "slice_number": dl.slice_number,
                                "chapter_id": dl.chapter_id,
                                "chapter_num": chapter.chap_num,  # Real chapter number (1-17)
                                "text": dl.slice_text
                            })

            print(f"   Found {len(lessons_to_process)} reading lessons")

            # Filter by lesson_id if specified
            if lesson_id:
                lessons_to_process = [l for l in lessons_to_process if l["lesson_id"] == lesson_id]
                if not lessons_to_process:
                    print(f"❌ Lesson {lesson_id} not found in course")
                    return
                print(f"   Filtering to lesson {lesson_id} only")

            # Sort lessons by day_number to get sequential order
            lessons_to_process.sort(key=lambda l: l["day_number"])

            # Add sequential_number to each lesson (1-105 for course_id=17)
            for seq_num, lesson in enumerate(lessons_to_process, start=1):
                lesson["sequential_number"] = seq_num

            # Group lessons by chapter number
            lessons_by_chapter = {}
            for lesson in lessons_to_process:
                ch_num = lesson["chapter_num"]  # Use real chapter number
                if ch_num not in lessons_by_chapter:
                    lessons_by_chapter[ch_num] = []
                lessons_by_chapter[ch_num].append(lesson)

            # Process each chapter
            print("\n4. Processing chapters and matching lessons...")
            results = []

            for chapter_num in sorted(lessons_by_chapter.keys()):
                # Find matching audiobook chapter by chapter number (1-17)
                audio_chapter_idx = None
                for idx, ch_data in chapter_paths.items():
                    # Extract chapter number from title
                    title = ch_data["info"].title
                    match = re.search(r'Chapter (\d+)', title)
                    if match and int(match.group(1)) == chapter_num:
                        audio_chapter_idx = idx
                        break

                if audio_chapter_idx is None:
                    print(f"\n  Chapter {chapter_num}: No matching audio chapter found")
                    continue

                ch_data = chapter_paths[audio_chapter_idx]
                ch_path = ch_data["path"]
                ch_info = ch_data["info"]

                print(f"\n  Chapter {chapter_num}: {ch_info.title}")
                print(f"    Audio: {ch_path.name}")

                # Transcribe chapter
                transcript = self.transcribe_chapter(ch_path, audio_chapter_idx)

                # Process each lesson in this chapter
                chapter_lessons = lessons_by_chapter[chapter_num]
                print(f"    Processing {len(chapter_lessons)} lessons...")

                for lesson_data in chapter_lessons:
                    # Try adaptive precision: high → medium → low
                    start_time, end_time, used_precision = self.find_text_with_adaptive_precision(
                        lesson_data["text"],
                        transcript,
                        lesson_id=lesson_data["lesson_id"]
                    )

                    if start_time is not None and end_time is not None:
                        if used_precision != self.precision:
                            print(f"      [INFO] Lesson {lesson_data['lesson_id']}: matched with {used_precision} precision (fallback from {self.precision})")
                        segment = LessonSegment(
                            lesson_id=lesson_data["lesson_id"],
                            day_number=lesson_data["day_number"],
                            slice_number=lesson_data["slice_number"],
                            chapter_id=lesson_data["chapter_id"],  # Use DB chapter_id for relation
                            text=lesson_data["text"][:100],
                            start_time=start_time,
                            end_time=end_time
                        )

                        # Check if lesson audio already exists
                        # NEW: Use stable filename format
                        expected_filename = generate_audio_filename(
                            course_id=course_id,
                            chapter_num=lesson_data["chapter_num"],
                            sequential_number=lesson_data["sequential_number"]
                        )
                        expected_audio_path = self.lessons_dir / expected_filename
                        should_extract = True

                        if expected_audio_path.exists():
                            if self.interactive:
                                response = input(f"      Lesson {lesson_data['lesson_id']} already exists. Overwrite? (y/n): ")
                                should_extract = response.lower() in ['y', 'yes']
                                if should_extract:
                                    # Delete the file so it will be re-extracted
                                    expected_audio_path.unlink()
                                    print(f"      Deleted existing file for re-extraction")
                            else:
                                print(f"      Lesson {lesson_data['lesson_id']} already exists, skipping...")
                                should_extract = False

                        # Extract audio if needed
                        if should_extract:
                            audio_path = self.extract_lesson_audio(
                                ch_path,
                                segment,
                                course_id=course_id,
                                chapter_num=lesson_data["chapter_num"],
                                sequential_number=lesson_data["sequential_number"]
                            )
                            if audio_path:
                                segment.audio_path = str(audio_path)
                                results.append(segment)
                                print(f"      Lesson {lesson_data['lesson_id']} (Day {lesson_data['day_number']}): "
                                      f"{start_time:.1f}s - {end_time:.1f}s ({end_time - start_time:.1f}s)")
                        else:
                            # Still add to results even if not extracted
                            segment.audio_path = str(expected_audio_path)
                            results.append(segment)
                    else:
                        print(f"      Lesson {lesson_data['lesson_id']}: Could not match text")

                # Interactive check after each chapter
                if self.interactive:
                    response = input(f"\n  Continue to next chapter? (y/n): ")
                    if response.lower() not in ['y', 'yes']:
                        print("\n  Stopping as requested...")
                        break

            # Save results
            print(f"\n5. Saving results...")
            results_path = self.output_dir / "lesson_segments.json"
            results_data = [
                {
                    "lesson_id": r.lesson_id,
                    "day_number": r.day_number,
                    "slice_number": r.slice_number,
                    "chapter_id": r.chapter_id,
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "duration": r.end_time - r.start_time,
                    "audio_path": r.audio_path
                }
                for r in results
            ]

            with open(results_path, 'w', encoding='utf-8') as f:
                json.dump(results_data, f, ensure_ascii=False, indent=2)

            print(f"\n{'='*60}")
            print(f"COMPLETE!")
            print(f"  Processed: {len(results)} lessons")
            print(f"  Output directory: {self.output_dir}")
            print(f"  Results saved to: {results_path}")
            print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Split audiobook into lesson segments")
    parser.add_argument("--m4b", required=True, help="Path to M4B audiobook file")
    parser.add_argument("--course-id", type=int, required=True, help="Book course ID from database")
    parser.add_argument("--output", help="Output directory (default: books/audio/<book_name>)")
    parser.add_argument("--ffmpeg", default="./ffmpeg", help="Path to ffmpeg binary")
    parser.add_argument(
        "--precision",
        choices=["low", "medium", "high"],
        default="medium",
        help="Matching precision: low (60%%), medium (70%%), high (80%%)"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive mode (prompt before overwriting files and after each chapter)"
    )
    parser.add_argument(
        "--transcripts-dir",
        help="Directory containing transcript JSON files (default: <output>/transcripts)"
    )
    parser.add_argument(
        "--lesson-id",
        type=int,
        help="Process only this specific lesson ID (optional)"
    )

    args = parser.parse_args()

    m4b_path = Path(args.m4b)
    if not m4b_path.exists():
        print(f"Error: M4B file not found: {m4b_path}")
        sys.exit(1)

    output_dir = args.output
    if not output_dir:
        output_dir = m4b_path.parent / m4b_path.stem

    splitter = AudioLessonSplitter(
        m4b_path=str(m4b_path),
        output_dir=str(output_dir),
        ffmpeg_path=args.ffmpeg,
        precision=args.precision,
        interactive=args.interactive,
        transcripts_dir=args.transcripts_dir
    )

    splitter.process_course(args.course_id, lesson_id=args.lesson_id)


if __name__ == "__main__":
    main()