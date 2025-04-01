from flask import request, session, g
from flask_babel import Babel

babel = Babel()


def get_locale():
    """
    Определяет язык пользователя на основе:
    1. Параметра в URL (?lang=ru)
    2. Значения в сессии
    3. Заголовков Accept-Language в браузере
    4. Язык по умолчанию - английский
    """
    # Проверяем наличие параметра в URL
    if 'lang' in request.args:
        lang = request.args.get('lang')
        session['lang'] = lang
        return lang

    # Проверяем сохраненный язык в сессии
    if 'lang' in session:
        return session['lang']

    # Определяем язык по заголовкам браузера
    return request.accept_languages.best_match(['en', 'ru'])


def init_babel(app):
    """Инициализация Flask-Babel с приложением Flask"""
    babel.init_app(app, locale_selector=get_locale)
    app.jinja_env.add_extension('jinja2.ext.i18n')

    @app.before_request
    def before_request():
        g.locale = get_locale()