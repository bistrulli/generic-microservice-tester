# Stage 1: Build C extension for GIL-releasing busy-wait
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY src/busy_wait.c .
RUN gcc -shared -fPIC -O2 -o busy_wait.so busy_wait.c

# Stage 2: Runtime image (no gcc, minimal footprint)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install Python dependencies
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy compiled C extension from builder stage
COPY --from=builder /build/busy_wait.so .

# Copy application code
COPY src/app.py .
COPY src/lqn_parser.py .

# Copy entrypoint
COPY docker/entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8080
CMD ["./entrypoint.sh"]
