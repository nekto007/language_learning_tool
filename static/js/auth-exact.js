document.addEventListener('DOMContentLoaded', function() {
  // Инициализация переключателя видимости пароля
  initPasswordToggle();
});

/**
 * Инициализация переключателя отображения пароля
 */
function initPasswordToggle() {
  const toggleButtons = document.querySelectorAll('.toggle-password');

  toggleButtons.forEach(button => {
    button.addEventListener('click', function() {
      const passwordInput = this.parentElement.querySelector('input');

      if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        this.innerHTML = '<i class="bi bi-eye-slash"></i>';
        this.setAttribute('aria-label', 'Hide password');
      } else {
        passwordInput.type = 'password';
        this.innerHTML = '<i class="bi bi-eye"></i>';
        this.setAttribute('aria-label', 'Show password');
      }

      // Фокус на поле ввода для лучшего UX
      passwordInput.focus();
    });
  });
}