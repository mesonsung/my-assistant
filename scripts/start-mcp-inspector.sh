#!/usr/bin/env bash
# Start MCP Inspector behind nginx on :6280 (UI + proxy same origin)
set -euo pipefail

HOST_IP="${HOST_IP:-10.147.45.178}"
TOKEN="${MCP_PROXY_AUTH_TOKEN:-$(openssl rand -hex 32)}"

# Inspector listens locally; nginx :6280 fronts both UI and proxy
export HOST=127.0.0.1
export MCP_AUTO_OPEN_ENABLED=false
export MCP_PROXY_AUTH_TOKEN="$TOKEN"
export NODE_TLS_REJECT_UNAUTHORIZED=0
export ALLOWED_ORIGINS="http://localhost:6280,http://127.0.0.1:6280,http://${HOST_IP}:6280,http://localhost:6274,http://127.0.0.1:6274,http://${HOST_IP}:6274"

echo "$TOKEN" > /tmp/mcp-inspector-token.txt

URL="http://${HOST_IP}:6280/?MCP_PROXY_AUTH_TOKEN=${TOKEN}&MCP_PROXY_FULL_ADDRESS=http%3A%2F%2F${HOST_IP}%3A6280&transport=streamable-http&serverUrl=https%3A%2F%2F10.0.39.1%2Fmcp"

echo "=============================================="
echo " MCP Inspector (single port via nginx)"
echo " Open ONLY this URL:"
echo " ${URL}"
echo "=============================================="
echo " Local:"
echo " http://127.0.0.1:6280/?MCP_PROXY_AUTH_TOKEN=${TOKEN}&MCP_PROXY_FULL_ADDRESS=http%3A%2F%2F127.0.0.1%3A6280&transport=streamable-http&serverUrl=https%3A%2F%2F10.0.39.1%2Fmcp"
echo "=============================================="
echo " Tip: Cursor port-forward only needs port 6280"
echo "=============================================="

exec npx -y @modelcontextprotocol/inspector
