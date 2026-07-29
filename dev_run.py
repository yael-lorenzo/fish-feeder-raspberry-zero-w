"""
Run the Fish Feeder web UI on a development machine (no Raspberry Pi hardware).

app.py imports gpiozero and shells out to the Pi camera tools, neither of which
exist on a laptop. This launcher stubs gpiozero so app.py imports cleanly, then
starts Flask. The motor/camera actions become harmless no-ops, but every page
and tab renders so you can work on the frontend.

Usage (Docker — recommended):
    docker compose up --build
    # open http://localhost:8000

Usage (bare, if you have Flask installed):
    python3 dev_run.py
    # open http://127.0.0.1:8000

Bind address/port come from DEV_HOST / DEV_PORT (defaults 127.0.0.1:8000).
The Docker setup sets DEV_HOST=0.0.0.0 so the container is reachable.

Notes:
- The background scheduler does NOT start here (it only runs under app.py's
  __main__ block), so nothing will try to "feed" while you develop.
- The Live View tab will show no frames (no camera), and the Logs tab will say
  journalctl is unavailable — both expected off-Pi.
"""
import os
import sys
import types

# --- Stub gpiozero so `from gpiozero import OutputDevice` works off-Pi ---
_fake_gpiozero = types.ModuleType("gpiozero")


class OutputDevice:
    def __init__(self, *args, **kwargs):
        self.value = 0

    def on(self):
        self.value = 1

    def off(self):
        self.value = 0


_fake_gpiozero.OutputDevice = OutputDevice
sys.modules["gpiozero"] = _fake_gpiozero

# Import AFTER the stub is in place.
import app  # noqa: E402

if __name__ == "__main__":
    # Port 8000 avoids the macOS AirPlay Receiver that often grabs 5000.
    # debug=True gives auto-reload while you edit templates/CSS.
    host = os.environ.get("DEV_HOST", "127.0.0.1")
    port = int(os.environ.get("DEV_PORT", "8000"))
    app.app.run(host=host, port=port, debug=True, threaded=True)
