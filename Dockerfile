FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements
COPY requirements.txt ./

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директорий для media
RUN mkdir -p media/video media/processed_audio media/transcriptions

# Порт API
EXPOSE 8000

# По умолчанию запускаем API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

