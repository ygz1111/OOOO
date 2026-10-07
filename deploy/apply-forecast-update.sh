#!/bin/sh
# Run only after uploading the verified incremental package to this ECS host.
set -eu
update_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=/opt/smartgrid-server
test "$(realpath "$project")" = "$project" || { echo 'Unexpected project path'; exit 1; }
test -f "$project/.env"
test -f "$project/deploy/docker-compose.server.yml"
cd "$update_dir"
sha256sum -c SHA256SUMS
cd "$project"
sh deploy/compose.sh config --quiet
container=$(sh deploy/compose.sh ps -aq smartgrid-api)
test -n "$container" || { echo 'Existing API container not found. This is not a first-install package.'; exit 1; }
old_image=$(docker inspect --format '{{.Image}}' "$container")
mkdir -p "$project/backups"
backup=$(mktemp -d "$project/backups/forecast-$(date +%Y%m%d-%H%M%S)-XXXXXX")
backup_tag="smartgrid-forecast-backup:$(basename "$backup")"
docker image tag "$old_image" "$backup_tag"
printf '%s\n' "$backup_tag" > "$backup/image-tag.txt"
printf '%s\n' "$backup" > "$project/backups/last-forecast-update.txt"
# Preserve all current source files and web assets. Do not read/copy credentials.
tar -czf "$backup/sources.tgz" backend/realtime_api frontend/dist
printf 'Backup: %s\n' "$backup"

# Reuse this server's working Python/TensorFlow installation; no registry pull.
docker build --pull=false --build-arg "BASE_IMAGE=$backup_tag" \
    -f "$update_dir/Dockerfile.forecast-update" \
    -t smartgrid-personal-smartgrid-api:latest "$update_dir"

for file in tf_realtime_feature_provider.py tf_split_service.py \
    services/live_forecast.py services/prediction_pipeline.py services/prediction_insight.py \
    routers/prediction.py routers/price.py routers/generation.py schemas/core.py; do
    cp "$update_dir/backend/realtime_api/$file" "$project/backend/realtime_api/$file"
done
# Keep old hashed assets for already open browser tabs. Never delete user files.
cp -a "$update_dir/frontend/dist/." "$project/frontend/dist/"
sh deploy/compose.sh up -d --no-deps --no-build --pull never --force-recreate smartgrid-api
sh deploy/compose.sh restart web
sh deploy/compose.sh ps
printf '\nUpdate installed; API may still be warming up. Check health and all forecast pages.\n'
printf 'Rollback backup: %s\n' "$backup"
printf 'No .env, Compose, database, Redis, model weights or dependencies were replaced.\n'
