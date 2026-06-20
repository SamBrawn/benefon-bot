FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для Pillow и других библиотек
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install pydantic==2.5.0
RUN pip install pydantic-core==2.14.1
RUN pip install -r requirements.txt

# Копирование всего проекта
COPY . .

# Открываем порт для Render
EXPOSE 8000

# Запуск бота
CMD ["python", "main.py"]
