FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LITELLM_TELEMETRY=False
WORKDIR /app
COPY services/api/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY services/api/app ./app
COPY services/api/migrations ./migrations
COPY services/api/alembic.ini ./alembic.ini
RUN useradd --create-home --uid 10001 wagl
USER wagl
EXPOSE 8000
CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]