#!/bin/sh
set -e

if [ -z "$BASIC_AUTH_USER" ] || [ -z "$BASIC_AUTH_PASSWORD" ]; then
  echo "ERROR: BASIC_AUTH_USER and BASIC_AUTH_PASSWORD must be set" >&2
  exit 1
fi

HASH=$(openssl passwd -apr1 "$BASIC_AUTH_PASSWORD")
echo "${BASIC_AUTH_USER}:${HASH}" > /etc/nginx/.htpasswd

echo "window.__env__ = { SENTRY_DSN: \"${SENTRY_FRONTEND_DSN}\" };" > /usr/share/nginx/html/env-config.js

exec nginx -g 'daemon off;'