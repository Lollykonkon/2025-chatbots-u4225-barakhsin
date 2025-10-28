FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source
COPY bot.py /app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]


