"""
Tests for password strength validator
Тесты валидатора стойкости паролей
"""
import pytest
from app.utils.password_validator import PasswordStrengthValidator


class TestPasswordStrengthValidator:
    """Тесты валидатора стойкости паролей"""

    def test_valid_strong_password(self):
        """Тест валидного сильного пароля"""
        # Пароль без последовательностей и с 4+ повторяющимися символами
        is_valid, errors = PasswordStrengthValidator.validate_password("MyP@ssw0rd2024")
        assert is_valid is True
        assert len(errors) == 0

    def test_too_short_password(self):
        """Тест слишком короткого пароля"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Short1!")
        assert is_valid is False
        assert any("минимум 8 символов" in err for err in errors)

    def test_too_long_password(self):
        """Тест слишком длинного пароля (>128 символов)"""
        long_password = "A" * 129 + "1!"
        is_valid, errors = PasswordStrengthValidator.validate_password(long_password)
        assert is_valid is False
        assert any("128 символов" in err for err in errors)

    def test_no_digits(self):
        """Тест пароля без цифр"""
        is_valid, errors = PasswordStrengthValidator.validate_password("StrongPassword!")
        assert is_valid is False
        assert any("цифр" in err for err in errors)

    def test_no_letters(self):
        """Тест пароля без букв"""
        is_valid, errors = PasswordStrengthValidator.validate_password("123456789!")
        assert is_valid is False
        assert any("букв" in err for err in errors)

    def test_no_uppercase(self):
        """Тест пароля без заглавных букв"""
        is_valid, errors = PasswordStrengthValidator.validate_password("weakpass123!")
        assert is_valid is False
        assert any("заглавн" in err for err in errors)

    def test_no_lowercase(self):
        """Тест пароля без строчных букв"""
        is_valid, errors = PasswordStrengthValidator.validate_password("WEAKPASS123!")
        assert is_valid is False
        assert any("строчн" in err for err in errors)

    def test_no_special_chars(self):
        """Тест пароля без специальных символов"""
        is_valid, errors = PasswordStrengthValidator.validate_password("WeakPass123")
        assert is_valid is False
        assert any("специальн" in err for err in errors)

    def test_common_password(self):
        """Тест распространенного слабого пароля"""
        is_valid, errors = PasswordStrengthValidator.validate_password("password123")
        assert is_valid is False
        assert any("распространен" in err for err in errors)

    def test_password_matches_username(self):
        """Тест пароля, совпадающего с именем пользователя"""
        is_valid, errors = PasswordStrengthValidator.validate_password(
            "testuser",
            username="testuser"
        )
        assert is_valid is False
        # Будет несколько ошибок, включая совпадение с username
        assert any("имен" in err.lower() for err in errors)

    def test_password_matches_email(self):
        """Тест пароля, совпадающего с частью email"""
        is_valid, errors = PasswordStrengthValidator.validate_password(
            "testuser",
            email="testuser@example.com"
        )
        assert is_valid is False
        assert any("email" in err for err in errors)

    def test_sequential_numbers(self):
        """Тест пароля с последовательными числами"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Pass123word!")
        assert is_valid is False
        assert any("последовательност" in err for err in errors)

    def test_repeated_chars(self):
        """Тест пароля с повторяющимися символами"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Passssword1!")
        assert is_valid is False
        assert any("повторяющихся" in err for err in errors)

    def test_sequential_letters(self):
        """Тест пароля с последовательными буквами"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Abcdefg123!")
        assert is_valid is False
        assert any("последовательност" in err for err in errors)

    def test_descending_sequence(self):
        """Тест пароля с убывающей последовательностью"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Pass321word!")
        assert is_valid is False
        assert any("последовательност" in err for err in errors)

    def test_valid_password_with_all_checks(self):
        """Тест полностью валидного пароля со всеми проверками"""
        is_valid, errors = PasswordStrengthValidator.validate_password(
            "MySecur3P@ssw0rd",
            username="different_user",
            email="other@example.com"
        )
        assert is_valid is True
        assert len(errors) == 0

    def test_multiple_errors(self):
        """Тест что возвращаются все ошибки"""
        is_valid, errors = PasswordStrengthValidator.validate_password("weak")
        assert is_valid is False
        # Должно быть несколько ошибок
        assert len(errors) > 3

    def test_edge_case_exactly_8_chars(self):
        """Тест пароля ровно 8 символов"""
        is_valid, errors = PasswordStrengthValidator.validate_password("Pass123!")
        # Может быть валидным или нет в зависимости от других проверок
        # Главное - проверяем что минимальная длина не вызывает ошибку
        assert not any("минимум 8 символов" in err for err in errors)

    def test_edge_case_exactly_128_chars(self):
        """Тест пароля ровно 128 символов"""
        password = "A" * 120 + "bC123!@#"  # Exactly 128 chars
        is_valid, errors = PasswordStrengthValidator.validate_password(password)
        # Не должно быть ошибки о превышении максимальной длины
        assert not any("128 символов" in err for err in errors)

    def test_descending_letter_sequence(self):
        """Тест пароля с убывающей буквенной последовательностью"""
        is_valid, errors = PasswordStrengthValidator.validate_password("P@ssw0rdCba!")
        assert is_valid is False
        assert any("последовательност" in err for err in errors)


class TestPasswordStrengthRating:
    """Тесты оценки силы пароля"""

    def test_weak_password_strength(self):
        """Тест слабого пароля"""
        strength = PasswordStrengthValidator.get_password_strength("weak")
        assert strength == 'weak'

    def test_medium_password_strength(self):
        """Тест пароля средней силы"""
        strength = PasswordStrengthValidator.get_password_strength("Medium123")
        assert strength == 'medium'

    def test_strong_password_strength(self):
        """Тест сильного пароля"""
        strength = PasswordStrengthValidator.get_password_strength("Strong123!")
        assert strength == 'strong'

    def test_very_strong_password_strength(self):
        """Тест очень сильного пароля"""
        strength = PasswordStrengthValidator.get_password_strength("VeryStr0ng!P@ssw0rd2024")
        assert strength == 'very_strong'

    def test_short_password_strength(self):
        """Тест что очень короткий пароль получает низкую оценку"""
        strength = PasswordStrengthValidator.get_password_strength("Pass1")
        assert strength in ['weak', 'medium']

    def test_long_password_strength(self):
        """Тест что длинный пароль с разнообразием получает высокую оценку"""
        long_password = "ThisIsAVeryLongAnd$ecureP@ssw0rd!"
        strength = PasswordStrengthValidator.get_password_strength(long_password)
        assert strength in ['strong', 'very_strong']

    def test_password_with_special_chars_bonus(self):
        """Тест что специальные символы дают бонус к силе"""
        strength_without = PasswordStrengthValidator.get_password_strength("Password123")
        strength_with = PasswordStrengthValidator.get_password_strength("Password123!")
        # С спецсимволами должно быть не хуже
        strengths = ['weak', 'medium', 'strong', 'very_strong']
        assert strengths.index(strength_with) >= strengths.index(strength_without)

    def test_sequential_chars_reduces_strength(self):
        """Тест что последовательности снижают силу пароля"""
        strength_good = PasswordStrengthValidator.get_password_strength("MyP@ssw0rd2024")
        strength_sequential = PasswordStrengthValidator.get_password_strength("MyP@ssw0rd123")
        # Пароль с последовательностью должен быть слабее
        strengths = ['weak', 'medium', 'strong', 'very_strong']
        assert strengths.index(strength_sequential) <= strengths.index(strength_good)

    def test_repeated_chars_reduces_strength(self):
        """Тест что повторяющиеся символы снижают силу"""
        strength_good = PasswordStrengthValidator.get_password_strength("MyP@ssw0rd!")
        strength_repeated = PasswordStrengthValidator.get_password_strength("MyP@ssssword!")
        # Пароль с повторениями должен быть слабее или равен
        strengths = ['weak', 'medium', 'strong', 'very_strong']
        assert strengths.index(strength_repeated) <= strengths.index(strength_good)
