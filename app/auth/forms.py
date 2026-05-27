from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from flask_babel import lazy_gettext as _l
from app.auth.models import User
from app.utils.password_validator import validate_password_strength


class LoginForm(FlaskForm):
    username_or_email = StringField(_l('Username or Email'), validators=[DataRequired(), Length(max=254)])
    password = PasswordField(_l('Password'), validators=[DataRequired(), Length(max=128)])
    remember_me = BooleanField(_l('Remember Me'))
    submit = SubmitField(_l('Sign In'))


class RegistrationForm(FlaskForm):
    username = StringField(_l('Username'), validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField(_l('Email'), validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(_l('Password'), validators=[DataRequired(), Length(min=8, max=128)])
    password2 = PasswordField(_l('Confirm Password'), validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField(_l('Register'))

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError(_l('Username already in use.'))

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError(_l('Email already registered.'))

    def validate_password(self, password):
        """Валидация стойкости пароля"""
        is_valid, errors = validate_password_strength(
            password.data,
            username=self.username.data if hasattr(self, 'username') else None,
            email=self.email.data if hasattr(self, 'email') else None
        )
        if not is_valid:
            # Объединяем все ошибки в одно сообщение
            error_message = ' '.join(errors)
            raise ValidationError(error_message)


class RequestResetForm(FlaskForm):
    """Form for requesting a password reset."""
    email = StringField(_l('Email'), validators=[
        DataRequired(),
        Email(),
        Length(max=254)
    ])
    submit = SubmitField(_l('Request Password Reset'))
    # NOTE: Do NOT add validate_email here — querying whether an email
    # exists would allow user enumeration.  The route always shows the
    # same "check your inbox" message regardless of whether the address
    # is registered.


class ResetPasswordForm(FlaskForm):
    """Form for resetting a password after receiving a reset token."""
    password = PasswordField(_l('New Password'), validators=[
        DataRequired(),
        Length(min=8, max=128)
    ])
    password2 = PasswordField(_l('Confirm New Password'), validators=[
        DataRequired(),
        EqualTo('password')
    ])
    submit = SubmitField(_l('Reset Password'))

    def validate_password(self, password):
        """Валидация стойкости пароля"""
        is_valid, errors = validate_password_strength(password.data)
        if not is_valid:
            error_message = ' '.join(errors)
            raise ValidationError(error_message)
