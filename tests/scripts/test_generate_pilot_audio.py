from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts"
_MODULE_KEY = "scripts_generate_pilot_audio"
if _MODULE_KEY not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _MODULE_KEY,
        SCRIPT_PATH / "generate_pilot_audio.py",
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_KEY] = _mod
    _mod.__package__ = ""
    _spec.loader.exec_module(_mod)
else:
    _mod = sys.modules[_MODULE_KEY]

Job = _mod.Job
synthesize = _mod.synthesize
_filled_gap_question = _mod._filled_gap_question


def _job(output_path: Path) -> Job:
    return Job(
        file="module_C1_10_test.json",
        lesson_number=4,
        lesson_type="grammar",
        audio_url="[sound:grammar_C1M10L4_ex37.mp3]",
        output_path=output_path,
        text="This is a test.",
        voice="en-US-AriaNeural",
        rate="+0%",
    )


def test_filled_gap_question_uses_correct_answer_for_tts():
    text = _filled_gap_question({
        "type": "listening_choice",
        "question": "We ___ happy",
        "correct": "are",
        "translation": "Мы счастливы",
    })

    assert text == "We are happy"


def test_synthesize_retries_transient_tts_timeout(monkeypatch, tmp_path):
    attempts = 0

    class FakeCommunicate:
        def __init__(self, text, voice, rate):
            self.text = text
            self.voice = voice
            self.rate = rate

        async def save(self, path):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("Connection timeout to host wss://speech.platform.bing.com")
            Path(path).write_bytes(b"mp3")

    monkeypatch.setattr(_mod.edge_tts, "Communicate", FakeCommunicate)

    output_path = tmp_path / "grammar_C1M10L4_ex37.mp3"
    asyncio.run(synthesize(_job(output_path), retries=2, retry_delay=0))

    assert attempts == 3
    assert output_path.read_bytes() == b"mp3"
    assert not (tmp_path / ".grammar_C1M10L4_ex37.mp3.tmp").exists()


def test_synthesize_keeps_existing_file_when_retries_are_exhausted(monkeypatch, tmp_path):
    class FakeCommunicate:
        def __init__(self, text, voice, rate):
            self.text = text
            self.voice = voice
            self.rate = rate

        async def save(self, path):
            Path(path).write_bytes(b"partial")
            raise TimeoutError("Connection timeout to host wss://speech.platform.bing.com")

    monkeypatch.setattr(_mod.edge_tts, "Communicate", FakeCommunicate)

    output_path = tmp_path / "grammar_C1M10L4_ex37.mp3"
    output_path.write_bytes(b"existing")

    try:
        asyncio.run(synthesize(_job(output_path), retries=1, retry_delay=0))
    except TimeoutError:
        pass
    else:
        raise AssertionError("synthesize should raise after retries are exhausted")

    assert output_path.read_bytes() == b"existing"
