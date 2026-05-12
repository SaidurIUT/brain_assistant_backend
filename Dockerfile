FROM python:3.12-slim AS api

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

FROM api AS worker

RUN apt-get update \
  && apt-get install -y --no-install-recommends libreoffice-writer \
  && rm -rf /var/lib/apt/lists/* \
  && python -m playwright install --with-deps chromium

CMD ["celery", "-A", "app.jobs.celery_app:celery_app", "worker", "--loglevel=info", "--concurrency=1", "-Q", "brain-jobs"]
