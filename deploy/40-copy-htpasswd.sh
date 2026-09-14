#!/bin/sh
set -e
if [ -f /etc/secrets/htpasswd ]; then
  cp /etc/secrets/htpasswd /etc/nginx/htpasswd
  chmod 644 /etc/nginx/htpasswd
fi
