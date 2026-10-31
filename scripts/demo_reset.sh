#!/usr/bin/env bash
set -euo pipefail

export APP_ENV=${APP_ENV:-demo}
export DEMO_RESET_ENABLED=${DEMO_RESET_ENABLED:-1}

python -m flask --app app:create_app demo-reset --seed
