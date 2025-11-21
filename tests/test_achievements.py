"""
Tests for achievements module
Тесты модуля достижений
"""
import pytest
from app.achievements.models import LessonGrade, UserStatistics
from app.achievements.seed import seed_achievements
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

    def test_seed_achievements_skips_if_exists(self, app, db_session):
        """Тест что seed_achievements пропускает если уже есть данные"""
        with app.app_context():
            # Создаем один achievement
            achievement = Achievement(
                code='test',
                name='Test',
                description='Test',
                icon='🎯',
                xp_reward=10,
                category='test'
            )
            db_session.add(achievement)
            db_session.commit()

            initial_count = Achievement.query.count()

            # Запускаем seed
            seed_achievements()

            # Проверяем что количество не изменилось
            assert Achievement.query.count() == initial_count
