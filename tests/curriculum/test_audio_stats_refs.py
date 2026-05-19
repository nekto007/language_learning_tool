from app.curriculum.routes.admin import _iter_lesson_audio_refs


def test_audio_stats_refs_include_nested_arrays_and_test_sections():
    content = {
        "sections": [
            {
                "rules": [
                    {
                        "examples": ["I am here. - Я здесь.", "You are here. - Ты здесь."],
                        "audio": [
                            "[sound:grammar_ex1.mp3]",
                            "[sound:grammar_ex2.mp3]",
                        ],
                    }
                ]
            }
        ],
        "cards": [
            {"english": "welcome", "audio": "[sound:pronunciation_en_welcome.mp3]"}
        ],
        "test_sections": [
            {
                "exercises": [
                    {"question": "Listen", "audio": "[sound:final_listen_1.mp3]"}
                ]
            }
        ],
        "audio_url": "/static/audio/immersion/dictation/a1_m1_dictation.mp3",
    }

    refs = {(filename, source) for _label, filename, source in _iter_lesson_audio_refs(content)}

    assert ("grammar_ex1.mp3", "grammar") in refs
    assert ("grammar_ex2.mp3", "grammar") in refs
    assert ("pronunciation_en_welcome.mp3", "card") in refs
    assert ("final_listen_1.mp3", "test") in refs
    assert ("a1_m1_dictation.mp3", "lesson") in refs
