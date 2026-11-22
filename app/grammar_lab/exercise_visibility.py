"""Keep retired material and its history out of new practice sessions."""


def active_exercise_clause():
    from app.grammar_lab.models import GrammarExercise

    # Missing flag = active for legacy topics not migrated yet. JSON extraction
    # compiles for PostgreSQL JSONB and the SQLite test compatibility type.
    return GrammarExercise.content["guided_retired"].as_boolean().isnot(True)
