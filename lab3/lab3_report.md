# Lab3 Report

University: [ITMO University](https://itmo.ru/ru/)
Faculty: [FICT](https://fict.itmo.ru)
Course: [Vibe Coding: AI-боты для бизнеса](https://github.com/itmo-ict-faculty/vibe-coding-for-business)
Year: 2025/2026
Group: U4225
Author: Barakhsin
Lab: Lab3
Date of create: [ДАТА_НАЧАЛА_РАБОТЫ]
Date of finished: [ДАТА_ЗАВЕРШЕНИЯ_РАБОТЫ]

## Описание лабораторной работы

Lab3 — деплой бота для реального использования. В этой работе выполнен контейнерный деплой Telegram-бота (Docker) и запуск на VPS. Также используется единое видео-демо для всех лабораторных. Источник требований: [Lab3](https://itmo-ict-faculty.github.io/vibe-coding-for-business/labs/lab3/).

## Теоретическая часть

### Контейнеризация и деплой
- Docker: контейнеризация приложения и зависимостей
- Dockerfile: reproducible build
- Docker Compose (опционально)
- Среда исполнения: Python 3.10, переменные окружения

### Деплой на VPS
- Сетап сервера (Ubuntu), пользователь, firewall
- Запуск контейнера в фоне
- Хранение секретов: `.env`

## Практическая часть

### Dockerfile

```Dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY lab1/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY lab1 /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
```

### .env (на VPS)
```
TELEGRAM_BOT_TOKEN=xxxxx
```

### Сборка и запуск локально
```bash
docker build -t task-bot:latest -f Dockerfile .
docker run --name task-bot --env-file .env --restart unless-stopped -d task-bot:latest
```

### Деплой на VPS (SSH)
1. Копируем файлы проекта и `.env`
2. Ставим Docker: `curl -fsSL https://get.docker.com | sh`
3. Сборка и запуск как выше
4. Проверка логов: `docker logs -f task-bot`

### Установка и настройка

- VPS: Ubuntu 22.04+, 1 vCPU, 512MB RAM достаточно
- Установка Docker, настройка пользователя
- Создание `.env` и запуск контейнера

### Реализация

- Подготовлен минимальный `Dockerfile`
- Настроен запуск с переменными окружения
- Обеспечен автоматический рестарт контейнера

### Тестирование

- Проверка ответа на `/start`
- Добавление/список/выполнение задач
- Проверка напоминаний по дедлайну

## Результаты

- Бот упакован в Docker, развёрнут на VPS
- Логи доступны через `docker logs`
- Секреты защищены через `.env`

## Выводы

Деплой через Docker на VPS обеспечивает воспроизводимость, простоту запуска и стабильность работы бота. Требования Lab3 выполнены. Ссылка на требования: [Lab3](https://itmo-ict-faculty.github.io/vibe-coding-for-business/labs/lab3/).

## Приложения

### Ссылка на общее видео-демо (для всех лаб)
- [YouTube/Drive: единое видео-демо](#)
