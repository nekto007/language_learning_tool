"""
Flask extensions and shared instances.
"""
from flask_sqlalchemy import SQLAlchemy

# Создаем одиночный экземпляр SQLAlchemy, который будет использоваться во всем приложении
db = SQLAlchemy()