# Development image for the Fish Feeder web UI — no Raspberry Pi hardware needed.
# Only Flask is required: dev_run.py stubs gpiozero, and the camera/motor calls
# are harmless no-ops off-Pi. This image is for local UI development, NOT for
# running on the Pi (the Pi uses setup_service.sh + systemd).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

# Copy the code so the image works standalone. In dev, docker-compose bind-mounts
# the project over /app, so your edits take effect live (with Flask auto-reload).
COPY . /app

ENV DEV_HOST=0.0.0.0 \
    DEV_PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python3", "dev_run.py"]
