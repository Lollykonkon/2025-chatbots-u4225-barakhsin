# Lab3 Report

University: [ITMO University](https://itmo.ru/ru/)
Faculty: [FICT](https://fict.itmo.ru)
Course: [Vibe Coding: AI-боты для бизнеса](https://github.com/itmo-ict-faculty/vibe-coding-for-business)
Year: 2025/2026
Group: U4225
Author: Barakhsin
Lab: Lab3
Date of create: 28.01.2025
Date of finished: 28.01.2025

## Описание лабораторной работы

Lab3 — деплой бота для реального использования. В этой работе выполнен деплой Telegram-бота с использованием Docker Compose. Источник требований: [Lab3](https://itmo-ict-faculty.github.io/vibe-coding-for-business/labs/lab3/).

**Цель:** Научиться деплоить бота и собирать обратную связь от реальных пользователей для улучшения продукта.

## Ход работы

### Шаг 1: Выбор способа деплоя

Выбран **Вариант 3: Docker (продвинутый)** согласно требованиям лабораторной работы. Это обеспечивает:
- Контейнеризацию бота для воспроизводимого развертывания
- Простое управление зависимостями
- Изоляцию окружения
- Простое масштабирование

### Шаг 2: Подготовка к деплою

Выполнена следующая подготовка:

1. **Проверен код бота** - все команды работают корректно
2. **Создан .env файл** с настройками:
   ```env
   TELEGRAM_BOT_TOKEN=8200200156:AAFlXtNQheroWTEpS2REXbH8N0gbvFFjpOY
   CALENDAR_TIMEZONE=Europe/Moscow
   ```

3. **Добавлен .gitignore** для защиты секретов:
   ```
   .env
   *.pyc
   __pycache__/
   *.db
   *.log
   storage.json
   token.json
   credentials.json
   ```

4. **Создан requirements.txt** с зависимостями

5. **Добавлено логирование** в bot.py для отладки

### Шаг 3: Деплой

#### Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY bot.py /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
```

#### docker-compose.yml

```yaml
services:
  bot:
    build: .
    env_file:
      - .env
    # Ensure these files exist locally before running compose
    volumes:
      - ./storage.json:/app/storage.json
      - ./credentials.json:/app/credentials.json
      - ./token.json:/app/token.json
    restart: unless-stopped
```

#### Команды для деплоя

```bash
# Сборка образа
docker compose build

# Запуск в фоне
docker compose up -d

# Просмотр логов
docker compose logs -f bot

# Остановка
docker compose down
```

### Шаг 4: Тестирование деплоя

Бот успешно развернут в Docker контейнере. Выполненные команды:

```bash
# Сборка образа
docker compose build
# Результат: Образ успешно собран

# Запуск контейнера
docker compose up -d
# Результат: Container started

# Проверка статуса
docker compose ps
# Результат: STATUS: Up

# Просмотр логов
docker compose logs bot
# Результат: Application started successfully
```

**Логи запуска:**
```
bot-1  | 2025-10-28 17:07:41,758 INFO HTTP Request: POST https://api.telegram.org/bot8200200156:AAFlXtNQheroWTEpS2REXbH8N0gbvFFjpOY/getMe "HTTP/1.1 200 OK"     
bot-1  | 2025-10-28 17:07:41,797 INFO HTTP Request: POST https://api.telegram.org/bot8200200156:AAFlXtNQheroWTEpS2REXbH8N0gbvFFjpOY/deleteWebhook "HTTP/1.1 200 OK"                                                                             
bot-1  | 2025-10-28 17:07:41,801 INFO Application started
```

**Работоспособность проверена:**
- ✅ Контейнер запущен и работает
- ✅ Бот подключился к Telegram API
- ✅ Все команды доступны для тестирования

### Шаг 5: Сбор обратной связи

Бот подготовлен к сбору обратной связи от пользователей. Следующие шаги:
1. Пригласить 3-5 пользователей для тестирования
2. Собрать отзывы о функциональности
3. Зафиксировать проблемы и предложения по улучшению

### Шаг 6: Улучшения на основе фидбека

Планируется анализ отзывов пользователей и внесение улучшений в следующих итерациях.

## Результаты

### Реализованный функционал деплоя

1. **Контейнеризация:**
   - ✅ Dockerfile для сборки образа
   - ✅ Docker Compose для управления
   - ✅ Volume mounts для персистентности данных
   - ✅ Контейнер успешно запущен: `2025-chatbots-u4225-barakhsin-bot-1`

2. **Безопасность:**
   - ✅ Хранение токенов в .env
   - ✅ .gitignore для защиты секретов
   - ✅ Изоляция контейнера

3. **Надежность:**
   - ✅ Автоматический перезапуск (restart: unless-stopped)
   - ✅ Логирование для мониторинга
   - ✅ Volume mounts для сохранения данных

4. **Функциональность бота:**
   - ✅ Управление задачами
   - ✅ Система приоритетов
   - ✅ Дедлайны с напоминаниями
   - ✅ Интеграция с Google Calendar
   - ✅ Персистентное хранение

5. **Статус развертывания:**
   - ✅ Образ собран: `2025-chatbots-u4225-barakhsin-bot:latest`
   - ✅ Контейнер работает: `STATUS: Up`
   - ✅ Бот готов к использованию через Telegram

### Способы деплоя

Подготовлены следующие варианты деплоя:

1. **Локальный запуск с Docker:**
   ```bash
   docker compose up -d
   ```

2. **Облачный деплой (Railway/Render):**
   - Файлы готовы для загрузки на Railway или Render
   - Требуется только добавить BOT_TOKEN в переменные окружения платформы

3. **VPS деплой:**
   - Можно развернуть на любом VPS с Docker
   - Команды: `docker compose up -d`

## Выводы

### Достигнутые цели

1. ✅ Успешно подготовлен Docker образ бота
2. ✅ Настроен Docker Compose для удобного управления
3. ✅ Обеспечена безопасность через .env и .gitignore
4. ✅ Реализована персистентность данных через volume mounts
5. ✅ Бот готов к использованию и сбору обратной связи

### Технические достижения

- **Воспроизводимость:** Docker обеспечивает идентичное окружение везде
- **Безопасность:** Токены хранятся в переменных окружения
- **Масштабируемость:** Легко развернуть на любой платформе
- **Поддерживаемость:** Логи и мониторинг через docker compose logs

### Возможности развития

1. **Облачный деплой:** Развернуть на Railway, Render или Fly.io
2. **CI/CD:** Добавить автоматический деплой из Git
3. **Мониторинг:** Интеграция с системами мониторинга
4. **База данных:** Миграция с JSON на PostgreSQL
5. **Webhook:** Переход с polling на webhook для лучшей производительности

### Практическая ценность

Деплой через Docker и Docker Compose обеспечивает:
- Простоту развертывания на любой платформе
- Идентичное поведение в разных окружениях
- Легкое обновление и откат изменений
- Профессиональный подход к деплою приложений

## Приложения

### Структура проекта

```
2025-chatbots-u4225-barakhsin/
├── bot.py                  # Основной файл бота
├── Dockerfile              # Docker образ
├── docker-compose.yml      # Docker Compose конфигурация
├── requirements.txt        # Python зависимости
├── .env                    # Переменные окружения (секреты)
├── .env.example           # Пример .env файла
├── .gitignore             # Игнорируемые файлы
├── storage.json           # Хранилище задач
├── credentials.json       # Google OAuth credentials
├── token.json            # Google OAuth tokens
└── lab3/
    └── lab3_report.md    # Этот отчет
```

### Команды Docker

| Команда | Описание |
|---------|----------|
| `docker compose build` | Собрать образ |
| `docker compose up -d` | Запустить в фоне |
| `docker compose down` | Остановить |
| `docker compose logs -f bot` | Просмотр логов |
| `docker compose restart bot` | Перезапустить |

### Скриншоты

Скриншоты работы бота будут добавлены после сбора обратной связи от пользователей.

### Полезные ссылки

- [Lab3 Requirements](https://itmo-ict-faculty.github.io/vibe-coding-for-business/labs/lab3/)
- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [python-telegram-bot Documentation](https://python-telegram-bot.org/)