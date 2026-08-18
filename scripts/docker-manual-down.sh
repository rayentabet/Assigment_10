#!/usr/bin/env bash
set -euo pipefail

# Tears down everything scripts/docker-manual-up.sh created, in reverse
# order. Named volumes are deliberately left in place (that's the point of a
# named volume - it survives container removal); pass --volumes to also wipe
# them.

NETWORK=robotics-net

echo "Stopping and removing containers..."
docker rm -f app-api component-manager-rest component-manager mcp-server qdrant 2>/dev/null || true

echo "Removing network..."
docker network rm "$NETWORK" 2>/dev/null || true

if [[ "${1:-}" == "--volumes" ]]; then
  echo "Removing named volumes..."
  docker volume rm qdrant_data component_manager_data app_chat_data app_generated 2>/dev/null || true
else
  echo "Named volumes kept: qdrant_data, component_manager_data, app_chat_data, app_generated"
  echo "  (rerun with --volumes to also remove them)"
fi
