#!/bin/sh
set -eu
deploy_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(dirname -- "$deploy_dir")
if [ ! -f "$project_root/.env" ]; then
    printf '%s\n' 'Run python3 deploy/setup_env.py first.' >&2
    exit 1
fi
exec docker compose --project-name smartgrid-personal --env-file "$project_root/.env" -f "$deploy_dir/docker-compose.server.yml" "$@"
