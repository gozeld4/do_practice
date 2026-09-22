FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]