# Language Learning Tool - Test Suite

Comprehensive test suite for the language learning application.

## Coverage Goals

- **100% JSON Module Validation**: All module JSON files validated for structure and content
- **85%+ Code Coverage**: Curriculum module code coverage target

## Test Structure

```
tests/
├── conftest.py                 # Pytest fixtures and configuration
├── test_json_modules.py        # 100% JSON validation tests
└── curriculum/
    ├── test_service.py         # Service layer tests
    ├── test_models.py          # Model tests
    └── test_validators.py      # Validation tests
```

## Installation

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage report
```bash
pytest --cov=app/curriculum --cov-report=html
```

### Run specific test file
```bash
pytest tests/test_json_modules.py
```

### Run tests by marker
```bash
# Run only JSON tests
pytest -m json

# Run only service tests
pytest -m service

# Skip slow tests
pytest -m "not slow"
```

### Run tests in parallel
```bash
pytest -n auto
```

## Test Categories

### JSON Module Tests (`test_json_modules.py`)

Tests all module JSON files for:
- Valid JSON structure
- Required fields presence
- Lesson type validity
- Question type validity
- Content quality
- Data integrity
- Module progression logic

**Coverage**: 100% of all JSON module files

**Test Classes**:
- `TestJSONModuleStructure`: Basic structure validation
- `TestLessonTypes`: All lesson types (vocabulary, quiz, text, etc.)
- `TestQuestionTypes`: All question types (multiple_choice, translation, etc.)
- `TestContentQuality`: Content completeness and quality
- `TestDataIntegrity`: Data consistency and integrity
- `TestModuleProgression`: Logical lesson ordering

### Service Layer Tests (`curriculum/test_service.py`)

Tests curriculum service functions:
- User progress tracking
- Lesson completion
- Quiz processing
- Matching question processing
- Text normalization
- Final test processing
- Lesson statistics
- Flashcard functions
- Grammar processing

**Coverage**: 85%+ of curriculum/service.py

**Test Classes**:
- `TestUserProgress`: Progress tracking functions
- `TestLessonCompletion`: Lesson completion logic
- `TestQuizProcessing`: Quiz submission processing
- `TestMatchingProcessing`: Matching questions
- `TestTextNormalization`: Text normalization
- `TestFinalTestProcessing`: Final test logic
- `TestLessonStatistics`: Statistics functions
- `TestCardFunctions`: Flashcard functions
- `TestEdgeCases`: Error handling

### Model Tests (`curriculum/test_models.py`)

Tests database models:
- Level model
- Module model
- Lesson model
- LessonProgress model
- TextContent model
- QuizQuestion model
- Model relationships
- Model timestamps

**Coverage**: All curriculum models

**Test Classes**:
- `TestLevelModel`: Level model tests
- `TestModuleModel`: Module model tests
- `TestLessonModel`: Lesson model tests
- `TestLessonProgressModel`: Progress model tests
- `TestTextContentModel`: Text content tests
- `TestQuizQuestionModel`: Quiz question tests

### Validator Tests (`curriculum/test_validators.py`)

Tests data validation functions:
- Lesson data validation
- Quiz question validation
- Module structure validation
- Input validation
- Error handling

**Coverage**: All validation functions

**Test Classes**:
- `TestLessonDataValidation`: Lesson data validators
- `TestQuizQuestionValidation`: Question validators
- `TestModuleStructureValidation`: Module validators

## Coverage Reports

### Generate HTML coverage report
```bash
pytest --cov=app/curriculum --cov-report=html
open htmlcov/index.html
```

### Generate terminal report
```bash
pytest --cov=app/curriculum --cov-report=term-missing
```

### Generate XML report (for CI/CD)
```bash
pytest --cov=app/curriculum --cov-report=xml
```

## Continuous Integration

The test suite is configured to:
- Fail if coverage drops below 85%
- Generate coverage reports in multiple formats
- Run all tests with verbose output
- Show test durations
- Fail on warnings in strict mode

## Writing New Tests

### Test File Naming
- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Using Fixtures

```python
def test_my_function(app, db_session, test_user):
    """Test description"""
    with app.app_context():
        # Your test code
        pass
```

### Available Fixtures

- `app`: Flask application
- `client`: Test client
- `db_session`: Database session
- `test_user`: Test user
- `admin_user`: Admin user
- `test_level`: Test level
- `test_module`: Test module
- `test_lesson_vocabulary`: Vocabulary lesson
- `test_lesson_quiz`: Quiz lesson
- `test_lesson_text`: Text lesson
- `test_quiz_questions`: Quiz questions
- `test_lesson_progress`: Lesson progress
- `authenticated_client`: Authenticated test client
- `admin_client`: Admin test client
- `json_module_files`: List of JSON module files

### Parametrized Tests

```python
@pytest.mark.parametrize('json_file', pytest.lazy_fixture('json_module_files'))
def test_all_json_files(json_file):
    # Test each JSON file
    pass
```

## Test Markers

- `@pytest.mark.slow`: Slow tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.unit`: Unit tests
- `@pytest.mark.json`: JSON validation tests
- `@pytest.mark.service`: Service layer tests
- `@pytest.mark.models`: Model tests

## Debugging Tests

### Run with verbose output
```bash
pytest -vv
```

### Show local variables on failure
```bash
pytest --showlocals
```

### Stop on first failure
```bash
pytest -x
```

### Run specific test
```bash
pytest tests/test_json_modules.py::TestJSONModuleStructure::test_all_json_files_exist
```

### Run last failed tests
```bash
pytest --lf
```

## Best Practices

1. **Write descriptive test names**: Test names should clearly describe what is being tested
2. **One assertion per test**: Keep tests focused and simple
3. **Use fixtures**: Reuse common test setup with fixtures
4. **Test edge cases**: Include tests for error conditions and edge cases
5. **Keep tests fast**: Mock external dependencies and use in-memory database
6. **Maintain coverage**: Aim for 85%+ coverage on curriculum module
7. **Update tests with code**: Keep tests in sync with code changes

## Troubleshooting

### Tests failing due to database
```bash
# Reset test database
rm instance/test.db
pytest
```

### ImportError issues
```bash
# Ensure Python path includes project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest
```

### Coverage too low
```bash
# Check what's not covered
pytest --cov=app/curriculum --cov-report=term-missing
```

## License

Same as main project license.