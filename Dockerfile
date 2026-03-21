FROM python:3.13-slim

ARG APP_GIT_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY .cache/gtfs-nl-min.zip ./.cache/gtfs-nl-min.zip
COPY src ./src

RUN printf '%s\n' "$APP_GIT_SHA" > .build-commit
RUN uv sync --locked

EXPOSE 8080

CMD ["uv", "run", "python", "-m", "src.api.app", "--host", "0.0.0.0", "--port", "8080"]
