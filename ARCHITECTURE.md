# Architecture Overview

## Project Structure

```
app/
├── admin/              # Admin panel
│   ├── routes.py      # Admin HTTP routes
│   └── services/      # Admin business logic
├── api/               # RESTful API endpoints
├── auth/              # Authentication & authorization
├── books/             # Book reading module
│   ├── routes.py
│   └── services/
├── curriculum/        # Structured learning curriculum
│   ├── routes/
│   └── services/
├── study/             # Vocabulary study system
│   ├── routes.py
│   ├── services/      # Business logic layer
│   │   ├── srs_service.py
│   │   ├── quiz_service.py
│   │   ├── deck_service.py
│   │   ├── stats_service.py
│   │   └── collection_topic_service.py
│   └── models.py
├── words/             # Word management
├── utils/             # Shared utilities
└── templates/         # Jinja2 templates
```

## Architecture Patterns

### Service Layer Pattern

The application follows a **Service Layer Architecture** where business logic is separated from HTTP handling:

```
User Request → Route (HTTP Layer) → Service (Business Logic) → Model (Data Layer) → Database
```

**Benefits:**
- Clear separation of concerns
- Improved testability
- Code reusability
- Easier maintenance

### Example

```python
# Route (HTTP Layer) - app/study/routes.py
@study.route('/leaderboard')
@login_required
def leaderboard():
    # Get data from service
    top_xp_users = StatsService.get_xp_leaderboard(limit=100)

    # Render template
    return render_template('study/leaderboard.html',
                         top_xp_users=top_xp_users)

# Service (Business Logic) - app/study/services/stats_service.py
class StatsService:
    @staticmethod
    def get_xp_leaderboard(limit: int = 100) -> List[Dict]:
        """Get XP leaderboard with optimized queries"""
        results = db.session.query(
            User.id, User.username, UserXP.total_xp
        ).join(UserXP).order_by(desc(UserXP.total_xp)).limit(limit).all()

        return [{'id': r.id, 'username': r.username, ...} for r in results]
```

## Key Components

### 1. Study Module

**Services:**
- `SRSService` - Spaced Repetition System (SM-2 algorithm)
- `DeckService` - Deck management and word operations
- `QuizService` - Quiz generation and scoring
- `GameService` - Matching game logic
- `StatsService` - Statistics and leaderboards
- `SessionService` - Study session tracking
- `CollectionTopicService` - Collection and topic management

**Features:**
- Daily study limits
- Card scheduling
- Progress tracking
- Bulk query optimization (no N+1 queries)

### 2. Curriculum Module

**Services:**
- `ProgressService` - User progress tracking
- `LessonService` - Lesson processing
- `CurriculumCacheService` - Optimized data loading
- `FinalTestGenerator` - Test generation

**Features:**
- CEFR levels (A0-C2)
- Modules and lessons
- Multiple lesson types (vocabulary, grammar, quiz, text, matching)
- Gamification (streaks, points, levels)

### 3. Books Module

**Services:**
- `BookService` - Book management
- `ReadingProgressService` - Progress tracking

**Features:**
- EPUB/PDF/DOCX support
- Word extraction
- Reading progress
- Vocabulary integration

### 4. Admin Module

**Services:**
- `UserManagementService` - User administration

**Features:**
- User management
- Content management
- Statistics dashboard

## Database Design

### Key Models

**User-related:**
- `User` - User accounts
- `UserWord` - User's vocabulary with status (new, learning, review, mastered)
- `UserCardDirection` - SRS card data (forward/backward)
- `StudySession` - Study sessions tracking

**Content:**
- `CollectionWords` - Word dictionary
- `Collection` - Word collections
- `Topic` - Thematic word groups
- `Lessons` - Curriculum lessons
- `Module` - Curriculum modules

**Progress:**
- `LessonProgress` - Lesson completion tracking
- `UserXP` - Experience points
- `UserAchievement` - Earned achievements

### Optimizations

1. **Bulk Queries** - Using `IN` clauses and set operations to avoid N+1 queries
2. **Eager Loading** - Using `joinedload` for related data
3. **Indexes** - On frequently queried fields
4. **Caching** - Redis for leaderboards and static data

## Performance Optimizations

### Query Optimization

```python
# ❌ Bad (N+1 queries)
for collection in collections:
    words_in_study = UserWord.query.filter_by(
        user_id=user_id, word_id__in=collection.words
    ).count()

# ✅ Good (Single bulk query)
user_word_ids = {
    row[0] for row in db.session.query(UserWord.word_id)
    .filter_by(user_id=user_id).all()
}
for collection in collections:
    words_in_study = sum(1 for word in collection.words
                        if word.id in user_word_ids)
```

### Caching Strategy

- **Application cache** - Flask-Caching for leaderboards (5 min TTL)
- **Query result cache** - For expensive queries
- **Static content** - Browser caching for CSS/JS

## Security

1. **Input Validation** - Using Marshmallow schemas
2. **XSS Protection** - HTML sanitization with bleach
3. **CSRF Protection** - Flask-WTF tokens
4. **Rate Limiting** - Flask-Limiter for API endpoints
5. **SQL Injection** - SQLAlchemy ORM (parameterized queries)

## API Design

### RESTful Endpoints

```
GET  /api/study/items          # Get study items
POST /api/study/review          # Submit card review
GET  /api/leaderboard           # Get leaderboard
POST /api/quiz/submit           # Submit quiz answers
```

### Response Format

```json
{
  "success": true,
  "data": {...},
  "message": "Operation completed"
}
```

## Testing Strategy

1. **Unit Tests** - Test services independently
2. **Integration Tests** - Test routes with database
3. **Test Fixtures** - Reusable test data with pytest fixtures
4. **Coverage Goal** - 70%+ code coverage

## Deployment

### Docker

```yaml
services:
  web:
    build: .
    depends_on:
      - db
      - redis

  db:
    image: postgres:13

  redis:
    image: redis:alpine
```

### Environment Variables

- `DATABASE_URL` - Database connection string
- `SECRET_KEY` - Flask secret key
- `REDIS_URL` - Redis connection (optional)
- `MAIL_*` - Email configuration

## Future Improvements

1. **Microservices** - Split large modules
2. **GraphQL** - For flexible API queries
3. **WebSockets** - Real-time updates
4. **Background Jobs** - Celery for heavy tasks
5. **Monitoring** - Application performance monitoring

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## References

- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Spaced Repetition](https://en.wikipedia.org/wiki/Spaced_repetition)
