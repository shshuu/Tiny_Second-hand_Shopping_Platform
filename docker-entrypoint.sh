#!/bin/sh
set -eu

# Docker named volumes are created as root.  Initialise only the two writable
# directories, then run Django as the non-root application account.
mkdir -p /app/media /app/staticfiles
chown -R appuser:appuser /app/media /app/staticfiles

exec su -s /bin/sh appuser -c '
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput --clear
  exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
'
