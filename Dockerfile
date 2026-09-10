FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY pyproject.toml /app/
COPY requirements.lock /app/
COPY backend /app/backend
COPY skills /app/skills
COPY evaluation /app/evaluation
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --create-home --uid 10001 pilot && mkdir -p /workspace/.repopilot && chown -R pilot:pilot /workspace
USER pilot
ENV REPOPILOT_DATA=/workspace/.repopilot REPOPILOT_REPO_ROOT=/workspace REPOPILOT_PROJECT_ROOT=/app PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["repopilot", "serve", "--host", "0.0.0.0"]
