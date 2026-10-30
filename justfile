set dotenv-load := false

default:
    @just --list

# Unit tests, lint, format
test:
    uv run pytest && uv run ruff check && uv run ruff format --check

# Build and start the dev image (Dagu UI on http://127.0.0.1:18080)
up:
    HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose up --build -d

# Run one recording page through the meeting workflow (a dry run unless .env says otherwise)
try id:
    docker compose exec -u hermes workflows sh -c 'id=$(aspen-steps claim {{id}}) && dagu start meeting -- DOC_ID=$id DRY_RUN="$DRY_RUN" ; echo "what it would write: .data/work/$id/would-write/"'

down:
    docker compose down
