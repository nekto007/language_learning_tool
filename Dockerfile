FROM python:3.13-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Устанавливаем gunicorn явно
RUN pip install gunicorn

# Загрузка ресурсов NLTK
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('averaged_perceptron_tagger'); nltk.download('wordnet'); nltk.download('words')"

# Копирование кода приложения
COPY . .

# Создадим директории для данных и медиа
RUN mkdir -p /app/data /app/media

# Переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV DATABASE_PATH=/app/data/language_learning.db

# Открываем порт для Flask
EXPOSE 5000

# Создаем скрипт для инициализации базы данных
RUN echo '#!/bin/bash\n\
# Создаем директории, если их нет\n\
mkdir -p /app/data\n\
touch /app/data/language_learning.db\n\
chmod 666 /app/data/language_learning.db\n\
echo "Created empty database file"' > /app/init_db.sh && chmod +x /app/init_db.sh

# Создаем скрипт запуска
RUN echo '#!/bin/bash\n\
# Экспортируем переменные окружения для базы данных\n\
export DATABASE_PATH=/app/data/language_learning.db\n\
\n\
# Проверяем, существует ли база данных\n\
if [ ! -f /app/data/language_learning.db ]; then\n\
  echo "Initializing database..."\n\
  # Создаем пустой файл базы данных\n\
  mkdir -p /app/data\n\
  touch /app/data/language_learning.db\n\
  chmod 666 /app/data/language_learning.db\n\
  echo "Created empty database file"\n\
fi\n\
\n\
# Запускаем Flask приложение\n\
echo "Starting Flask application..."\n\
if command -v gunicorn &> /dev/null; then\n\
  exec gunicorn --bind 0.0.0.0:5000 app:app\n\
else\n\
  echo "Gunicorn not found, using Flask development server"\n\
  exec flask run --host=0.0.0.0 --port=5000\n\
fi' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Запуск через entrypoint
CMD ["/app/entrypoint.sh"]