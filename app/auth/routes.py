# app/auth/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.utils.db import db
from app.auth.models import User
from app.auth.forms import LoginForm, RegistrationForm
from datetime import datetime

auth = Blueprint('auth', __name__)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            # Check if user is active
            if not user.is_active:
                flash('Your account is inactive. Please contact an administrator.', 'danger')
                return render_template('auth/login.html', form=form)

            # Log in the user
            login_user(user, remember=form.remember_me.data)

            # Update last login timestamp
            user.last_login = datetime.utcnow()
            db.session.commit()

            # Redirect to requested page or dashboard
            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('words.dashboard')
            return redirect(next_page)
        else:
            flash('Invalid username or password', 'danger')

    return render_template('auth/login.html', form=form)


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('words.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            active=True  # Set user as active by default
        )
        user.set_password(form.password.data)

        try:
            db.session.add(user)
            db.session.commit()

            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed. Error: {str(e)}', 'danger')

    return render_template('auth/register.html', form=form)


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
