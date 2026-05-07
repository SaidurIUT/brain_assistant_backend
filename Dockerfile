FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir "."

EXPOSE 8010

CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8010"]

