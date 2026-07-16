FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv

FROM python:3.12-slim@sha256:c3d81d25b3154142b0b42eb1e61300024426268edeb5b5a26dd7ddf64d9daf28 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/glint-venv \
    HOME=/home/glint \
    PATH="/opt/glint-venv/bin:/usr/local/bin:$PATH"

WORKDIR /workspace

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 glint \
    && useradd --system --uid 10001 --gid glint --home-dir /home/glint --create-home --shell /usr/sbin/nologin glint

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN chown -R glint:glint /workspace /opt/glint-venv /home/glint

USER glint

CMD ["/opt/glint-venv/bin/python", "-m", "services.worker.app.main", "once"]
