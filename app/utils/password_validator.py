"""
Утилиты для валидации стойкости паролей
"""
import re
from typing import Tuple, List


# Список наиболее распространенных слабых паролей
COMMON_PASSWORDS = {
    'password', 'password123', '12345678', 'qwerty', 'abc123',
    'monkey', '1234567', 'letmein', 'trustno1', 'dragon',
    'baseball', 'iloveyou', 'master', 'sunshine', 'ashley',
    'bailey', 'passw0rd', 'shadow', '123123', '654321',
    'superman', 'qazwsx', 'michael', 'football', 'admin',
    'admin123', 'root', 'toor', 'pass', 'test'
}


class PasswordStrengthValidator:
    """Валидатор стойкости паролей"""

    @staticmethod
    def validate_password(password: str, username: str = None, email: str = None) -> Tuple[bool, List[str]]:
        """
        Проверяет стойкость пароля

        Args:
            password: Пароль для проверки
            username: Имя пользователя (опционально, для проверки совпадений)
            email: Email пользователя (опционально, для проверки совпадений)

        Returns:
            Tuple[bool, List[str]]: (is_valid, list_of_errors)
        """
        errors = []

        # 1. Минимальная длина
        if len(password) < 8:
            errors.append("Пароль должен содержать минимум 8 символов")

        # 2. Максимальная длина (защита от DoS)
        if len(password) > 128:
            errors.append("Пароль не должен превышать 128 символов")

        # 3. Наличие цифр
        if not re.search(r'\d', password):
            errors.append("Пароль должен содержать хотя бы одну цифру")

        # 4. Наличие букв
        if not re.search(r'[a-zA-Z]', password):
            errors.append("Пароль должен содержать хотя бы одну букву")

        # 5. Наличие заглавных букв
        if not re.search(r'[A-Z]', password):
            errors.append("Пароль должен содержать хотя бы одну заглавную букву")

        # 6. Наличие строчных букв
        if not re.search(r'[a-z]', password):
            errors.append("Пароль должен содержать хотя бы одну строчную букву")

        # 7. Наличие специальных символов (опционально, но рекомендуется)
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
            errors.append("Рекомендуется использовать специальные символы (!@#$%^&* и т.д.)")

        # 8. Проверка на общие слабые пароли
        if password.lower() in COMMON_PASSWORDS:
            errors.append("Этот пароль слишком распространен и небезопасен")

        # 9. Проверка на совпадение с username
        if username and password.lower() == username.lower():
            errors.append("Пароль не должен совпадать с именем пользователя")

        # 10. Проверка на совпадение с частью email
        if email:
            email_parts = email.lower().split('@')
            if email_parts and password.lower() == email_parts[0]:
                errors.append("Пароль не должен совпадать с email")

        # 11. Проверка на последовательности
        if PasswordStrengthValidator._has_sequential_chars(password):
            errors.append("Пароль не должен содержать последовательности символов (abc, 123)")

        # 12. Проверка на повторяющиеся символы
        if PasswordStrengthValidator._has_repeated_chars(password):
            errors.append("Пароль не должен содержать более 3 повторяющихся символов подряд")

        return len(errors) == 0, errors

    @staticmethod
    def _has_sequential_chars(password: str, min_length: int = 3) -> bool:
        """Проверяет наличие последовательных символов"""
        # Проверка числовых последовательностей
        for i in range(len(password) - min_length + 1):
            substring = password[i:i + min_length]
            if substring.isdigit():
                # Проверяем возрастающую последовательность
                if all(ord(substring[j]) == ord(substring[j - 1]) + 1 for j in range(1, len(substring))):
                    return True
                # Проверяем убывающую последовательность
                if all(ord(substring[j]) == ord(substring[j - 1]) - 1 for j in range(1, len(substring))):
                    return True

        # Проверка буквенных последовательностей
        for i in range(len(password) - min_length + 1):
            substring = password[i:i + min_length].lower()
            if substring.isalpha():
                # Проверяем возрастающую последовательность
                if all(ord(substring[j]) == ord(substring[j - 1]) + 1 for j in range(1, len(substring))):
                    return True
                # Проверяем убывающую последовательность
                if all(ord(substring[j]) == ord(substring[j - 1]) - 1 for j in range(1, len(substring))):
                    return True

        return False

    @staticmethod
    def _has_repeated_chars(password: str, max_repeats: int = 3) -> bool:
        """Проверяет наличие повторяющихся символов"""
        for i in range(len(password) - max_repeats):
            if all(password[i] == password[i + j] for j in range(max_repeats + 1)):
                return True
        return False

    @staticmethod
    def get_password_strength(password: str) -> str:
        """
        Оценивает силу пароля

        Returns:
            str: 'weak', 'medium', 'strong', 'very_strong'
        """
        score = 0

        # Длина
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if len(password) >= 16:
            score += 1

        # Разнообразие символов
        if re.search(r'[a-z]', password):
            score += 1
        if re.search(r'[A-Z]', password):
            score += 1
        if re.search(r'\d', password):
            score += 1
        if re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
            score += 2

        # Отсутствие слабых паттернов
        if not PasswordStrengthValidator._has_sequential_chars(password):
            score += 1
        if not PasswordStrengthValidator._has_repeated_chars(password):
            score += 1

        # Классификация
        if score <= 3:
            return 'weak'
        elif score <= 5:
            return 'medium'
        elif score <= 7:
            return 'strong'
        else:
            return 'very_strong'


def validate_password_strength(password: str, username: str = None, email: str = None) -> Tuple[bool, List[str]]:
    """
    Удобная функция-обертка для валидации пароля

    Args:
        password: Пароль для проверки
        username: Имя пользователя (опционально)
        email: Email пользователя (опционально)

    Returns:
        Tuple[bool, List[str]]: (is_valid, list_of_errors)
    """
    return PasswordStrengthValidator.validate_password(password, username, email)