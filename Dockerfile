FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
COPY main.py ./

RUN pip install --no-cache-dir .

EXPOSE 8765

CMD ["ozon-ord-sync", "api", "--api-host", "0.0.0.0", "--api-port", "8765"]
