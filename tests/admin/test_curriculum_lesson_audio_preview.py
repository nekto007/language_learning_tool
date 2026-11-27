"""Render audio links through the real administrative lesson view."""

from bs4 import BeautifulSoup
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.curriculum.models import Lessons, Module


def _audio_links(
    admin_client: FlaskClient, db_session: scoped_session, module: Module, kind: str, content: dict,
) -> list[str]:
    lesson = Lessons(module_id=module.id, number=97, order=97, title='Audio preview', type=kind, content=content)
    db_session.add(lesson)
    db_session.commit()
    response = admin_client.get(f'/curriculum/admin/lesson/{lesson.id}/view')
    assert response.status_code == 200
    db_session.refresh(lesson)
    assert lesson.content == content
    html = BeautifulSoup(response.data, 'html.parser')
    return [str(link['href']) for link in html.select('#pretty-view a[href]')]


def test_lesson_audio_preview_resolves_local_and_preserves_working_urls(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module,
) -> None:
    signed = 'https://media.example.test/a.mp3?part=2&signature=a%2Bb'
    lesson = {
        'audio': '[sound:synthetic-lesson.mp3]',
        'exercises': [
            {'audio': '[sound:synthetic-exercise.mp3]'},
            {'audio_url': '/static/audio/existing.mp3'},
            {'audio_url': signed, 'audio': 'unused.mp3'},
            {'audio_url': 'http://audio.example.test/legacy.ogg'},
            {'audio': '//media.example.test/old.mp3'},
            {'audio': 'static/audio/relative.mp3'},
            {'audio_clip_url': {'src': 'audio/clip.mp3'}},
            {'audio': 'bare.wav'},
        ],
    }
    assert _audio_links(admin_client, db_session, test_module, 'listening_quiz', lesson) == [
        '/static/audio/synthetic-lesson.mp3',
        '/static/audio/synthetic-exercise.mp3',
        '/static/audio/existing.mp3',
        signed,
        'http://audio.example.test/legacy.ogg',
        '//media.example.test/old.mp3',
        '/static/audio/relative.mp3',
        '/static/audio/clip.mp3',
        '/static/audio/bare.wav',
    ]


def test_section_audio_preview_skips_invalid_refs_and_uses_valid_fallbacks(
    admin_client: FlaskClient, db_session: scoped_session, test_module: Module,
) -> None:
    lesson = {
        'audio_url': 'https://[invalid',
        'audio': {'url': []},
        'test_sections': [
            {'title': 'Listening', 'audio': '[sound:synthetic-section.mp3]', 'exercises': [
                {'audio': '[sound:synthetic-final.mp3]'},
                {'audio_url': True, 'audio': '/media/fallback'},
                {'audio': '[sound:]'},
                {'audio': '[sound:unfinished.wav'},
                {'audio': {'src': 42}},
                {'audio': 'https://media.example.test:broken/file'},
                {'audio': 'https://'},
                {'audio': '[sound:' + 'x' * 4097 + '.mp3]'},
                {'audio': '../lost.mp3'},
                {'audio': []},
            ]},
        ],
    }
    assert _audio_links(admin_client, db_session, test_module, 'final_test', lesson) == [
        '/static/audio/synthetic-section.mp3',
        '/static/audio/synthetic-final.mp3',
        '/media/fallback',
    ]
