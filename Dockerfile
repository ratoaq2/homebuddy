FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.15-slim AS build

COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies first, so a code change does not install them again.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

COPY homebuddy ./homebuddy
RUN uv sync --locked --no-dev --no-editable


FROM python:3.15-slim

COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH

RUN useradd --create-home homebuddy
USER homebuddy
WORKDIR /home/homebuddy

EXPOSE 8080

# homebuddy reads the configuration file from the work directory:
#   docker run --rm -p 127.0.0.1:8080:8080 --env-file .env -v ./homebuddy.yml:/home/homebuddy/homebuddy.yml:ro homebuddy
CMD ["homebuddy", "--host", "0.0.0.0", "--no-show"]
