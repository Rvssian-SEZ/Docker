#!/bin/sh
# Runs the test suite against a throwaway Postgres container.
# Must be run on a host with Docker and the itops2_net network already
# present (i.e. the docker-test host, after `docker compose up` has run
# at least once). Never touches the real itops2/itops2-db containers.
#
# Usage: ./scripts/run_tests.sh   (run from the itops2/ repo root)
set -e

NET=itops2_net
DB_CONTAINER="itops2-test-db-$$"
IMAGE_TAG=itops2-test:latest

cleanup() {
  docker rm -f "$DB_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting throwaway Postgres ($DB_CONTAINER)..."
docker run -d --name "$DB_CONTAINER" --network "$NET" \
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
  postgres:16-alpine >/dev/null

echo "Waiting for it to accept connections..."
i=0
until docker exec "$DB_CONTAINER" pg_isready -U test -d test >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "Postgres did not become ready in time" >&2
    exit 1
  fi
  sleep 1
done

echo "Building test image..."
docker build -q -t "$IMAGE_TAG" . >/dev/null

echo "Running migrations + pytest..."
docker run --rm --network "$NET" \
  -e DATABASE_URL="postgresql+asyncpg://test:test@${DB_CONTAINER}:5432/test" \
  "$IMAGE_TAG" \
  sh -c "pip install --quiet -r requirements-dev.txt && alembic upgrade head && pytest -q"
