"""
Tests for import_module.py - JSON module import functionality
Тесты импорта модулей из JSON файлов
"""
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from import_module import import_module_from_json
from app.curriculum.models import CEFRLevel, Module, Lessons


class TestImportModuleBasic:
    """Базовые тесты импорта модулей"""

    def test_import_valid_module(self, app, db_session):
        """Тест успешного импорта валидного модуля"""
        import uuid
        with app.app_context():
            # Create unique level code
            level_code = uuid.uuid4().hex[:2].upper()
            # Create unique module ID
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            # Создаем тестовый JSON
            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Test Module",
                    "title_en": "Test Module EN",
                    "description": "Test description",
                    "level": level_code,
                    "lessons": [
                        {
                            "id": 1,
                            "title": "Vocabulary Lesson",
                            "order": 0,
                            "type": "vocabulary",
                            "xp_reward": 50,
                            "grammar_focus": "Test grammar",
                            "content": {
                                "vocabulary": [
                                    {
                                        "english": "hello",
                                        "russian": "привет",
                                        "pronunciation": "həˈloʊ"
                                    }
                                ]
                            }
                        }
                    ]
                }
            }

            # Создаем уровень
            level = CEFRLevel(code=level_code, name='Beginner', description='Beginner level', order=1)
            db_session.add(level)
            db_session.commit()

            # Создаем временный JSON файл
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                # Импортируем модуль
                result = import_module_from_json(temp_path)

                assert result is True

                # Проверяем что модуль создан
                module = Module.query.filter_by(number=module_id).first()
                assert module is not None
                assert module.title == "Test Module"
                assert module.level_id == level.id
                assert module.raw_content == test_data['module']

                # Проверяем что урок создан
                lessons = Lessons.query.filter_by(module_id=module.id).all()
                assert len(lessons) == 1
                assert lessons[0].title == "Vocabulary Lesson"
                assert lessons[0].type == "vocabulary"

            finally:
                # Удаляем временный файл
                Path(temp_path).unlink()
                # Cleanup module and level
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()
                # Delete the created level
                level_to_delete = CEFRLevel.query.filter_by(code=level_code).first()
                if level_to_delete:
                    db_session.delete(level_to_delete)
                    db_session.commit()

    def test_import_missing_module_key(self, app, db_session):
        """Тест импорта JSON без ключа 'module'"""
        with app.app_context():
            test_data = {"invalid": "data"}

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is False
            finally:
                Path(temp_path).unlink()

    def test_import_creates_missing_level(self, app, db_session):
        """Тест создания уровня если он отсутствует - создается A1"""
        import uuid
        with app.app_context():
            # Use a random level code that doesn't exist
            level_code = uuid.uuid4().hex[:2].upper()
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Test Module",
                    "title_en": "Test Module EN",
                    "description": "Test",
                    "level": level_code,  # Non-existent level
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)

                assert result is True

                # Проверяем что создан/использован уровень A1 (fallback level)
                level = CEFRLevel.query.filter_by(code='A1').first()
                assert level is not None
                assert level.name == 'Beginner'

                # Module should be using A1 level
                module = Module.query.filter_by(number=module_id).first()
                assert module is not None
                assert module.level_id == level.id

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()

    def test_import_uses_existing_level(self, app, db_session, test_level):
        """Тест использования существующего уровня"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Test Module",
                    "title_en": "Test Module EN",
                    "description": "Test",
                    "level": test_level.code,  # Use code from fixture
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)

                assert result is True

                # Проверяем что используется существующий уровень
                module = Module.query.filter_by(number=module_id).first()
                assert module.level_id == test_level.id

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()


class TestImportModuleLessonTypes:
    """Тесты маппинга типов уроков"""

    @pytest.mark.parametrize('lesson_type,expected_type', [
        ('vocabulary', 'vocabulary'),
        ('grammar', 'grammar'),
        ('quiz', 'quiz'),
        ('flashcards', 'card'),
        ('listening', 'matching'),
        ('reading', 'text'),
        ('listening_immersion', 'text'),
        ('test', 'final_test'),
        ('unknown_type', 'quiz'),  # default
    ])
    def test_lesson_type_mapping(self, app, db_session, test_level, lesson_type, expected_type):
        """Тест маппинга различных типов уроков"""
        with app.app_context():
            test_data = {
                "module": {
                    "id": 99,
                    "title": "Type Test Module",
                    "title_en": "Type Test",
                    "description": "Test",
                    "level": test_level.code,  # Use level from fixture
                    "lessons": [
                        {
                            "id": 1,
                            "title": f"{lesson_type} lesson",
                            "order": 0,
                            "type": lesson_type,
                            "content": {}
                        }
                    ]
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                lesson = Lessons.query.filter_by(title=f"{lesson_type} lesson").first()
                assert lesson is not None
                assert lesson.type == expected_type

            finally:
                Path(temp_path).unlink()
                # Очищаем созданный модуль
                module = Module.query.filter_by(number=99).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()


class TestImportModuleExistingModule:
    """Тесты обработки существующих модулей"""

    @patch('builtins.input', return_value='n')
    def test_import_existing_module_cancel(self, mock_input, app, db_session, test_level, test_module):
        """Тест отмены при попытке импорта существующего модуля"""
        with app.app_context():
            test_data = {
                "module": {
                    "id": test_module.number,  # используем номер существующего модуля
                    "title": "New Module",
                    "title_en": "New Module EN",
                    "description": "Test",
                    "level": test_level.code,  # Use level from fixture
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)

                # Должно вернуть False так как пользователь отменил
                assert result is False

                # Проверяем что старый модуль не изменился
                module = Module.query.get(test_module.id)
                assert module.title == test_module.title

            finally:
                Path(temp_path).unlink()

    @patch('builtins.input', return_value='y')
    def test_import_existing_module_replace(self, mock_input, app, db_session, test_level, test_module):
        """Тест замены существующего модуля"""
        with app.app_context():
            old_title = test_module.title
            test_data = {
                "module": {
                    "id": test_module.number,
                    "title": "Replaced Module",
                    "title_en": "Replaced Module EN",
                    "description": "New description",
                    "level": test_level.code,  # Use level from fixture
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)

                assert result is True

                # Проверяем что модуль заменен
                module = Module.query.filter_by(
                    level_id=test_level.id,
                    number=test_module.number
                ).first()
                assert module.title == "Replaced Module"
                assert module.title != old_title

            finally:
                Path(temp_path).unlink()


class TestImportModuleContent:
    """Тесты сохранения контента уроков"""

    def test_import_saves_raw_content(self, app, db_session, test_level):
        """Тест сохранения raw_content модуля"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Raw Content Test",
                    "title_en": "Raw Content Test EN",
                    "description": "Test description",
                    "level": "A1",
                    "custom_field": "custom_value",
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                module = Module.query.filter_by(number=module_id).first()
                assert module.raw_content == test_data['module']
                assert module.raw_content['custom_field'] == 'custom_value'

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()

    def test_import_saves_lesson_content(self, app, db_session, test_level):
        """Тест сохранения content урока"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000
            vocabulary_data = [
                {"english": "test", "russian": "тест", "pronunciation": "test"}
            ]

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Lesson Content Test",
                    "title_en": "Lesson Content Test EN",
                    "description": "Test",
                    "level": "A1",
                    "lessons": [
                        {
                            "id": 1,
                            "title": "Vocabulary",
                            "order": 0,
                            "type": "vocabulary",
                            "content": {
                                "vocabulary": vocabulary_data
                            }
                        }
                    ]
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                lesson = Lessons.query.filter_by(title="Vocabulary").first()
                assert lesson.content is not None
                assert 'vocabulary' in lesson.content
                assert lesson.content['vocabulary'] == vocabulary_data

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()


class TestImportModuleEdgeCases:
    """Тесты граничных случаев"""

    def test_import_empty_lessons(self, app, db_session, test_level):
        """Тест импорта модуля без уроков"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Empty Lessons Module",
                    "title_en": "Empty Lessons",
                    "description": "Test",
                    "level": "A1",
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                module = Module.query.filter_by(number=module_id).first()
                assert module is not None
                assert len(module.lessons) == 0

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()

    def test_import_multiple_lessons(self, app, db_session, test_level):
        """Тест импорта модуля с несколькими уроками"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Multiple Lessons",
                    "title_en": "Multiple Lessons",
                    "description": "Test",
                    "level": "A1",
                    "lessons": [
                        {
                            "id": i,
                            "title": f"Lesson {i}",
                            "order": i,
                            "type": "vocabulary",
                            "content": {}
                        }
                        for i in range(10)
                    ]
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                module = Module.query.filter_by(number=module_id).first()
                assert len(module.lessons) == 10

                # Проверяем порядок уроков
                lessons = sorted(module.lessons, key=lambda l: l.number)
                for i, lesson in enumerate(lessons):
                    assert lesson.title == f"Lesson {i}"
                    assert lesson.number == i

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()

    def test_import_with_database_error(self, app, db_session, test_level):
        """Тест обработки ошибки базы данных"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Error Test Module",
                    "title_en": "Error Test",
                    "description": "Test",
                    "level": "A1",
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                # Мокаем db.session.commit чтобы вызвать исключение
                with patch('app.utils.db.db.session.commit', side_effect=Exception('Database error')):
                    result = import_module_from_json(temp_path)

                    # Должно вернуть False при ошибке
                    assert result is False

                    # Проверяем что модуль не был создан
                    module = Module.query.filter_by(number=module_id).first()
                    assert module is None

            finally:
                Path(temp_path).unlink()

    def test_import_default_level(self, app, db_session):
        """Тест использования уровня по умолчанию (A1) когда level не указан"""
        import uuid
        with app.app_context():
            module_id = int(uuid.uuid4().hex[:6], 16) % 100000

            test_data = {
                "module": {
                    "id": module_id,
                    "title": "Default Level Module",
                    "title_en": "Default Level",
                    "description": "Test",
                    # level не указан - должен использоваться A1
                    "lessons": []
                }
            }

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(test_data, f)
                temp_path = f.name

            try:
                result = import_module_from_json(temp_path)
                assert result is True

                # Проверяем что создан уровень A1
                level = CEFRLevel.query.filter_by(code='A1').first()
                assert level is not None

                module = Module.query.filter_by(number=module_id).first()
                assert module.level_id == level.id

            finally:
                Path(temp_path).unlink()
                # Cleanup
                module = Module.query.filter_by(number=module_id).first()
                if module:
                    db_session.delete(module)
                    db_session.commit()