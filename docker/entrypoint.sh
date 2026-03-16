#!/bin/sh
# This script acts as the container's entrypoint.
# It reads environment variables to configure Gunicorn, providing sane defaults.

# Read the GUNICORN_WORKERS variable, defaulting to 2 if not set.
WORKERS=${GUNICORN_WORKERS:-2}

# Read the GUNICORN_THREADS variable, defaulting to 1 for process-based architecture.
# Process-based mode (threads=1) provides accurate CPU timing with delta tracking.
THREADS=${GUNICORN_THREADS:-1}

echo "Starting Gunicorn with ${WORKERS} workers and ${THREADS} threads (process-based mode for accurate CPU timing)."

# Execute Gunicorn.
# The 'exec' command replaces the shell process with the Gunicorn process.
# --worker-class sync: Ensures synchronous workers for predictable CPU timing
# --access-logfile - : Tells Gunicorn to write access logs to stdout.
exec gunicorn --workers ${WORKERS} --threads ${THREADS} --worker-class sync --bind 0.0.0.0:8080 --access-logfile - app:app

