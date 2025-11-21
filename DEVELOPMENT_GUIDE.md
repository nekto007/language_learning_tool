# Development Guide

Quick reference for developers working on this project.

## Project Setup

```bash
# Clone and setup
git clone <repo-url>
cd language_learning_tool_new
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Environment
cp .env.example .env
# Edit .env with your settings

# Database
flask db upgrade

# Run
flask run
```

## Architecture Overview

### Service Layer Pattern

Always use services for business logic:

```python
# ❌ Bad - Logic in route
@app.route('/stats')
def stats():
    stats = db.session.query(...).filter(...).all()
    # 50 lines of processing
    return render_template('stats.html', data=stats)

# ✅ Good - Logic in service
@app.route('/stats')
def stats():
    stats_data = StatsService.get_user_stats(current_user.id)
    return render_template('stats.html', data=stats_data)
```

### Module Structure

```
app/module_name/
├── __init__.py
├── routes.py          # HTTP endpoints (thin layer)
├── models.py          # Database models
├── forms.py           # WTForms
├── services/          # Business logic (thick layer)
│   ├── __init__.py
│   └── service_name.py
└── templates/
```

## Coding Standards

### 1. Service Methods

```python
class MyService:
    @staticmethod
    def get_user_data(user_id: int) -> Dict:
        """
        Get user data with statistics

        Args:
            user_id: User ID

        Returns:
            Dictionary with user data and stats
        """
        # Implementation
        pass
```

**Guidelines:**
- Use type hints
- Add docstrings
- Use `@staticmethod` for stateless methods
- Return dictionaries or lists for complex data
- Keep methods focused (single responsibility)

### 2. Routes

```python
@blueprint.route('/endpoint')
@login_required
def endpoint():
    """Endpoint description"""
    # 1. Get data from service
    data = Service.get_data(current_user.id)

    # 2. Render or return JSON
    return render_template('template.html', data=data)
```

**Guidelines:**
- Keep routes thin (< 20 lines)
- Use services for business logic
- Add route docstrings
- Handle errors appropriately

### 3. Database Queries

**Avoid N+1 queries:**

```python
# ❌ Bad - N+1 query problem
for user in users:
    user.word_count = UserWord.query.filter_by(user_id=user.id).count()

# ✅ Good - Single bulk query
word_counts = db.session.query(
    UserWord.user_id,
    func.count(UserWord.id)
).group_by(UserWord.user_id).all()
word_count_map = dict(word_counts)
for user in users:
    user.word_count = word_count_map.get(user.id, 0)
```

**Use set operations for membership checks:**

```python
# ✅ Efficient lookup
user_word_ids = {
    row[0] for row in db.session.query(UserWord.word_id)
    .filter_by(user_id=user_id).all()
}
for word in words:
    is_studying = word.id in user_word_ids  # O(1) lookup
```

### 4. Datetime Handling

```python
# ✅ Always use timezone-aware datetime
from datetime import datetime, timezone

now = datetime.now(timezone.utc)  # Not datetime.utcnow()
```

## Common Tasks

### Adding a New Feature

1. **Create service method:**
```python
# app/module/services/my_service.py
class MyService:
    @staticmethod
    def new_feature(user_id: int) -> Dict:
        # Business logic here
        return {'status': 'success'}
```

2. **Add route:**
```python
# app/module/routes.py
@blueprint.route('/new-feature')
@login_required
def new_feature():
    result = MyService.new_feature(current_user.id)
    return jsonify(result)
```

3. **Add tests:**
```python
# tests/test_my_service.py
def test_new_feature(app, user):
    result = MyService.new_feature(user.id)
    assert result['status'] == 'success'
```

### Database Migrations

```bash
# Create migration
flask db migrate -m "Description of changes"

# Review migration file in migrations/versions/

# Apply migration
flask db upgrade

# Rollback if needed
flask db downgrade
```

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/test_my_service.py

# With coverage
pytest --cov=app --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Key Services

### Study Module

- **SRSService** - Spaced repetition logic
  - `get_due_cards()` - Get cards due for review
  - `process_card_review()` - Update card after review
  - `check_daily_limits()` - Check study limits

- **DeckService** - Deck management
  - `create_deck()` - Create new deck
  - `add_words_to_deck()` - Add words to deck
  - `sync_deck()` - Sync deck with latest words

- **StatsService** - Statistics
  - `get_user_stats()` - User statistics
  - `get_leaderboard()` - Leaderboard data
  - `get_achievements_by_category()` - Achievement data

### Curriculum Module

- **ProgressService** - Progress tracking
  - `update_progress_with_grading()` - Update lesson progress
  - `get_user_level_progress()` - Get user progress by level

- **CurriculumCacheService** - Optimized data loading
  - `get_levels_with_progress()` - Levels with progress (cached)
  - `get_gamification_stats()` - Gamification data

## Performance Tips

### 1. Use Bulk Operations

```python
# ✅ Bulk insert
db.session.bulk_insert_mappings(UserWord, word_dicts)
db.session.commit()
```

### 2. Use Caching

```python
from app.utils.cache import cache

@cache.cached(timeout=300)  # 5 minutes
def get_expensive_data():
    return expensive_query()
```

### 3. Eager Loading

```python
# ✅ Use joinedload for related data
users = User.query.options(
    joinedload(User.words)
).filter_by(active=True).all()
```

## Security Guidelines

1. **Input Validation** - Always validate user input
```python
from marshmallow import Schema, fields

class MySchema(Schema):
    name = fields.Str(required=True)
    age = fields.Int(validate=lambda x: x >= 0)

schema = MySchema()
data = schema.load(request.json)
```

2. **XSS Protection** - Sanitize HTML
```python
from app.curriculum.security import sanitize_html

clean_html = sanitize_html(user_input)
```

3. **CSRF Protection** - Use Flask-WTF
```python
from flask_wtf import FlaskForm

class MyForm(FlaskForm):
    # CSRF token automatically included
    pass
```

## Git Workflow

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes and commit
git add .
git commit -m "Add feature description"

# Update from master
git fetch origin
git rebase origin/master

# Push
git push origin feature/my-feature
```

### Commit Messages

Use conventional commits:

```
feat: Add new feature
fix: Fix bug in X
refactor: Refactor Y for better performance
docs: Update documentation
test: Add tests for Z
chore: Update dependencies
```

## Debugging

### Flask Debug Mode

```bash
# In .env
FLASK_DEBUG=1

# Run
flask run
```

### Database Queries

```python
# Print SQL queries
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

### IPython Shell

```bash
flask shell

# In shell
from app import db
from app.study.models import UserWord
UserWord.query.filter_by(user_id=1).all()
```

## Resources

- [Architecture Documentation](ARCHITECTURE.md)
- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [pytest Documentation](https://docs.pytest.org/)

## Getting Help

- Check existing services for similar functionality
- Review ARCHITECTURE.md for design patterns
- Ask team members in Slack/Discord
- Check GitHub issues

## Common Issues

### Issue: Import errors

**Solution:** Check if `__init__.py` exports are correct

```python
# app/module/__init__.py
from .service import MyService

__all__ = ['MyService']
```

### Issue: Database locked (SQLite)

**Solution:** Use PostgreSQL in development or reduce concurrent queries

### Issue: N+1 query problems

**Solution:** Use bulk queries or eager loading (see above)

---

Happy coding! 🚀
