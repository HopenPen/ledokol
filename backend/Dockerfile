FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --extra mcp --extra ml --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY models/catboost_flow ./models/catboost_flow
RUN uv sync --no-dev --extra mcp --extra ml && uv pip install "psycopg[binary]>=3.2"
# Не root: приложению не нужны права на систему.
# Зависимости доступны для чтения; приложению нужен доступ на запись только в рабочий каталог.
RUN useradd --create-home appuser && chown appuser /app
USER appuser
EXPOSE 8000
# Схема БД — только миграциями: сначала upgrade head, потом API.
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]
