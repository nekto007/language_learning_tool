# Test Safety Documentation

## CRITICAL: Database Protection

Тесты имеют **три уровня защиты** от случайного использования production базы данных:

### Защита 1: Отдельный `.env.test`
- Тесты автоматически загружают `.env.test` вместо `.env`
- В `.env.test` явно указано `DATABASE_URL=sqlite:///:memory:`

### Защита 2: Запрет PostgreSQL/MySQL
```python
if 'postgresql' in db_uri or 'mysql' in db_uri:
    raise RuntimeError("CRITICAL: Tests are trying to use production database!")
```

### Защита 3: Требование суффикса `_test`
```python
if ':memory:' not in db_uri:
    if '_test' not in db_uri:
        raise RuntimeError("Test database must have '_test' suffix!")
```

## Запуск тестов

### Базовый запуск
```bash
pytest tests/
```

### С покрытием кода
```bash
pytest tests/ --cov=app/curriculum --cov-report=html
```

### Конкретный тест
```bash
pytest tests/test_curriculum_models.py::TestCEFRLevelModel -v
```

## Структура тестов

```
tests/
├── conftest.py                    # Фикстуры и конфигурация
├── test_curriculum_models.py      # Тесты моделей БД
├── test_curriculum_service.py     # Тесты бизнес-логики
├── test_curriculum_validators.py  # Тесты валидаторов
├── test_import_module.py          # Тесты импорта JSON модулей
└── TEST_SAFETY.md                 # Эта документация
```

## Цели покрытия

- **Общая цель**: 85% покрытие кода `app/curriculum`
- **Текущее состояние**: Проверяется при каждом запуске
- **Критичные модули**:
  - `service.py` - основная бизнес-логика
  - `validators.py` - валидация данных
  - `models.py` - модели БД

## Безопасность

**НИКОГДА** не удаляйте проверки безопасности в `conftest.py`!

Если тест падает с ошибкой `CRITICAL: Tests are trying to use production database!`:
1. ✅ **Это ХОРОШО** - защита сработала
2. ❌ **НЕ УБИРАЙТЕ** проверку
3. ✅ **ИСПРАВЬТЕ** конфигурацию теста

## Фикстуры

Основные фикстуры доступные в тестах:
- `app` - Flask приложение для тестов
- `client` - Тестовый клиент
- `db_session` - Сессия БД
- `test_user` - Тестовый пользователь
- `test_level` - Тестовый CEFR уровень
- `test_module` - Тестовый модуль
- `test_lesson_vocabulary` - Тестовый урок (vocabulary)
- `test_lesson_quiz` - Тестовый урок (quiz)

## Отладка

### Verbose output
```bash
pytest tests/ -vv
```

### Показать локальные переменные при ошибке
```bash
pytest tests/ --showlocals
```

### Остановиться на первой ошибке
```bash
pytest tests/ -x
```

### Запустить только проваленные тесты
```bash
pytest tests/ --lf
```

## Coverage Reports

После запуска тестов с `--cov-report=html`:
```bash
open htmlcov/index.html
```

Это откроет детальный отчет по покрытию кода.