FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (copy only requirements first for better caching)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Копируем только необходимые файлы и директории
# Не копируем аудиофайлы
COPY run.py .
COPY main.py .
COPY babel.cfg .
COPY cli.py .
COPY convert_fb2_to_txt.py .
COPY app app/
COPY config config/
# Добавляем другие нужные файлы/папки, если необходимо

# Создаем директорию для аудио файлов, но НЕ копируем сами файлы
# Они будут монтироваться через volume
RUN mkdir -p /app/app/temp
RUN mkdir -p /app/app/static/audio
RUN mkdir -p /app/app/static/uploads/covers

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=run.py \
    FLASK_ENV=production

# Set permissions
#RUN chmod -R 755 /app

# Run application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "--graceful-timeout", "30", "run:app"]
