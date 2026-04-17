"""
Tests for achievements module
Тесты модуля достижений
"""
import pytest
from app.achievements.models import LessonGrade, UserStatistics
from app.achievements.seed import INITIAL_ACHIEVEMENTS, seed_achievements
from app.study.models import Achievement


class TestLessonGradeModel:
    """Тесты модели LessonGrade"""

    def test_calculate_grade_a(self):
        """Тест расчета оценки A"""
        assert LessonGrade.calculate_grade(95.0) == 'A'
        assert LessonGrade.calculate_grade(90.0) == 'A'

    def test_calculate_grade_b(self):
        """Тест расчета оценки B"""
        assert LessonGrade.calculate_grade(85.0) == 'B'
        assert LessonGrade.calculate_grade(80.0) == 'B'

    def test_calculate_grade_c(self):
        """Тест расчета оценки C"""
        assert LessonGrade.calculate_grade(75.0) == 'C'
        assert LessonGrade.calculate_grade(70.0) == 'C'

    def test_calculate_grade_d(self):
        """Тест расчета оценки D"""
        assert LessonGrade.calculate_grade(65.0) == 'D'
        assert LessonGrade.calculate_grade(60.0) == 'D'

    def test_calculate_grade_f(self):
        """Тест расчета оценки F"""
        assert LessonGrade.calculate_grade(50.0) == 'F'
        assert LessonGrade.calculate_grade(0.0) == 'F'

    def test_grade_color_property(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест свойства grade_color"""
        with app.app_context():
            grade = LessonGrade(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                score=95.0,
                grade='A'
            )
            db_session.add(grade)
            db_session.commit()

            assert grade.grade_color == '#10b981'

    def test_grade_name_property(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест свойства grade_name"""
        with app.app_context():
            grade = LessonGrade(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                score=95.0,
                grade='A'
            )
            db_session.add(grade)
            db_session.commit()

            assert grade.grade_name == 'Отлично'

    def test_grade_repr(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест __repr__ метода"""
        with app.app_context():
            grade = LessonGrade(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                score=85.0,
                grade='B'
            )
            db_session.add(grade)
            db_session.commit()

            repr_str = repr(grade)
            assert 'LessonGrade' in repr_str
            assert str(test_user.id) in repr_str
            assert str(test_lesson_vocabulary.id) in repr_str
            assert 'B' in repr_str


class TestUserStatisticsModel:
    """Тесты модели UserStatistics"""

    def test_create_user_statistics(self, app, db_session, test_user):
        """Тест создания статистики пользователя"""
        with app.app_context():
            stats = UserStatistics(
                user_id=test_user.id,
                total_lessons_completed=10,
                total_score_sum=850.0
            )
            db_session.add(stats)
            db_session.commit()

            assert stats.id is not None
            assert stats.total_lessons_completed == 10
            assert stats.total_score_sum == 850.0

    def test_average_score_property(self, app, db_session, test_user):
        """Тест свойства average_score"""
        with app.app_context():
            stats = UserStatistics(
                user_id=test_user.id,
                total_lessons_completed=10,
                total_score_sum=850.0
            )
            db_session.add(stats)
            db_session.commit()

            assert stats.average_score == 85.0

    def test_average_score_zero_lessons(self, app, db_session, test_user):
        """Тест average_score при нуле уроков"""
        with app.app_context():
            stats = UserStatistics(
                user_id=test_user.id,
                total_lessons_completed=0,
                total_score_sum=0.0
            )
            db_session.add(stats)
            db_session.commit()

            assert stats.average_score == 0.0

    def test_total_grade_count_property(self, app, db_session, test_user):
        """Тест свойства total_grade_count"""
        with app.app_context():
            stats = UserStatistics(
                user_id=test_user.id,
                grade_a_count=5,
                grade_b_count=3,
                grade_c_count=2,
                grade_d_count=1,
                grade_f_count=0
            )
            db_session.add(stats)
            db_session.commit()

            assert stats.total_grade_count == 11

    def test_user_statistics_repr(self, app, db_session, test_user):
        """Тест __repr__ метода"""
        with app.app_context():
            stats = UserStatistics(user_id=test_user.id)
            db_session.add(stats)
            db_session.commit()

            repr_str = repr(stats)
            assert 'UserStatistics' in repr_str
            assert str(test_user.id) in repr_str


class TestSeedAchievements:
    """Тесты функции seed_achievements"""

    def test_seed_achievements_creates_achievements(self, app, db_session):
        """Тест создания achievements при первом запуске"""
        with app.app_context():
            # Убеждаемся что БД пустая
            Achievement.query.delete()
            db_session.commit()

            # Запускаем seed
            seed_achievements()

            # Проверяем что создались achievements
            count = Achievement.query.count()
            assert count > 0
            assert count >= 38  # Минимум 38 achievements из INITIAL_ACHIEVEMENTS

    def test_seed_achievements_skips_existing_codes(self, app, db_session):
        """Seed is idempotent: existing codes are not duplicated, new ones added."""
        with app.app_context():
            # Populate with a badge that overlaps with seed data
            Achievement.query.delete()
            db_session.commit()

            existing = Achievement(
                code='first_lesson',
                name='Kept',
                description='Pre-existing',
                icon='🎯',
                xp_reward=10,
                category='lessons'
            )
            db_session.add(existing)
            db_session.commit()

            seed_achievements()

            # Existing record kept unchanged
            kept = Achievement.query.filter_by(code='first_lesson').one()
            assert kept.name == 'Kept'

            # Total count now matches the seed list size (1 kept + rest inserted)
            assert Achievement.query.count() == len(INITIAL_ACHIEVEMENTS)

            # Calling again does nothing new
            seed_achievements()
            assert Achievement.query.count() == len(INITIAL_ACHIEVEMENTS)


class TestMissionBadges:
    """Тесты mission-specific бейджей в seed-данных"""

    EXPECTED_CODES = {
        'mission_first',
        'mission_progress_5',
        'mission_repair_5',
        'mission_reading_5',
        'mission_week_perfect',
        'mission_early_bird',
        'mission_night_owl',
        'mission_variety_3',
        'mission_speed_demon',
    }

    def test_all_mission_badges_defined(self):
        """All expected mission badges exist in INITIAL_ACHIEVEMENTS."""
        codes = {b['code'] for b in INITIAL_ACHIEVEMENTS}
        missing = self.EXPECTED_CODES - codes
        assert not missing, f'Missing mission badges: {missing}'

    def test_mission_badges_have_category_mission(self):
        """Every mission badge has category='mission'."""
        mission_badges = [b for b in INITIAL_ACHIEVEMENTS if b['code'] in self.EXPECTED_CODES]
        for badge in mission_badges:
            assert badge['category'] == 'mission', (
                f"Badge {badge['code']} has category={badge['category']!r}, expected 'mission'"
            )

    def test_mission_badges_required_fields(self):
        """Every mission badge has code, name, description, icon, xp_reward, category."""
        mission_badges = [b for b in INITIAL_ACHIEVEMENTS if b['code'] in self.EXPECTED_CODES]
        for badge in mission_badges:
            assert badge.get('code')
            assert badge.get('name')
            assert badge.get('description')
            assert badge.get('icon')
            assert isinstance(badge.get('xp_reward'), int) and badge['xp_reward'] > 0
            assert badge.get('category') == 'mission'

    def test_all_badge_codes_unique(self):
        """No duplicate codes across all seed badges (mission + existing)."""
        codes = [b['code'] for b in INITIAL_ACHIEVEMENTS]
        assert len(codes) == len(set(codes)), 'Duplicate badge codes in INITIAL_ACHIEVEMENTS'

    def test_mission_badges_do_not_clash_with_existing_codes(self):
        """Mission badge codes do not collide with pre-existing codes."""
        other_codes = {
            b['code'] for b in INITIAL_ACHIEVEMENTS if b['code'] not in self.EXPECTED_CODES
        }
        assert not (self.EXPECTED_CODES & other_codes)

    def test_seed_inserts_mission_badges(self, app, db_session):
        """seed_achievements inserts mission badges into the DB."""
        with app.app_context():
            Achievement.query.delete()
            db_session.commit()

            seed_achievements()

            db_codes = {code for (code,) in db_session.query(Achievement.code).all()}
            assert self.EXPECTED_CODES.issubset(db_codes)

            # Each mission badge in DB has category='mission'
            mission_rows = Achievement.query.filter(
                Achievement.code.in_(self.EXPECTED_CODES)
            ).all()
            assert all(row.category == 'mission' for row in mission_rows)
