import os
import time
import json
import threading
from datetime import datetime
import subprocess
from flask import Flask, render_template, Response, redirect, url_for, send_from_directory, request
from gpiozero import OutputDevice

app = Flask(__name__)

# --- HARDWARE SETUP ---
motor_pins = [OutputDevice(17), OutputDevice(18), OutputDevice(27), OutputDevice(22)]

step_sequence = [
    [1,0,0,0], [1,1,0,0], [0,1,0,0], [0,1,1,0],
    [0,0,1,0], [0,0,1,1], [0,0,0,1], [1,0,0,1]
]

# Traffic light for the camera: True means streaming, False means paused for a photo
camera_streaming_allowed = True

# --- SCHEDULE / FEED CONFIG ---
SCHEDULE_FILE = "schedule.json"
# One motor "quarter" = a quarter of a full physical rotation.
QUARTER_ROTATION = 0.25
# Serialize hardware access so a manual feed and a scheduled feed never overlap.
feed_lock = threading.Lock()

def spin_feeder_motor(rotations=1):
    """
    Spins the 28BYJ-48 stepper motor using the working nested loop structure,
    calibrated precisely to hit 1.0 full turn.
    """
    print(f"Motor spinning started ({rotations} rotations)...")

    # Calibrated base multiplier derived from your hardware's 1.5 turn output
    # 683 loops * 8 steps per sequence = ~5,464 total steps (1 full physical turn)
    steps_needed = int(684 * rotations)

    for _ in range(steps_needed):
        for step in step_sequence:
            for pin, state in zip(motor_pins, step):
                pin.value = state
            # This 1ms delay inside your original sequence was perfect
            time.sleep(0.001)

    # Cleanly cut power to prevent overheating
    for pin in motor_pins:
        pin.off()

    print("Motor spinning finished.")

# --- LIGHTWEIGHT SNAPSHOT STREAM ---
def capture_single_frame():
    #global camera_streaming_allowed
    #camera_streaming_allowed = False
    """Uses the fast rpicam-still immediate mode to capture a lightweight JPEG byte array"""
    cmd = [
        "rpicam-still",
        "-t", "1",                  # Fast 1ms warmup timeout
        "--width", "1920",           # Lower resolution to save memory
        "--height", "1080",
        "-e", "jpg",                # Output raw JPEG format
        "-o", "-"                   # Pipe output directly to stdout (RAM)
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3)
        #camera_streaming_allowed = True
        return result.stdout
    except Exception as e:
        print(f"Camera capture error: {e}")
        #camera_streaming_allowed = True
        return None

def generate_stream_frames():
    global camera_streaming_allowed  # Tell Python to look at the global traffic light variable
    while True:
        # If the feed button was pressed, pause and yield the camera
        if not camera_streaming_allowed:
            time.sleep(0.1)  # Sleep briefly and check again
            continue

        frame = capture_single_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        time.sleep(1.0) # Refresh rate: exactly 1 photo per second

# --- SCHEDULE STORAGE (JSON, no DB needed) ---
def load_schedule():
    """Return the schedule dict {'entries': [...]}, tolerating a missing/corrupt file."""
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    return data
        except (json.JSONDecodeError, OSError) as e:
            print(f"Could not read schedule file: {e}")
    return {"entries": []}

def save_schedule(data):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def clean_quarters(value, default=4):
    """Coerce user input into a whole number of quarter-turns (minimum 1)."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default

# --- CORE FEED ACTION (shared by manual button and scheduler) ---
def perform_feed(quarters=4):
    """Spin the motor by `quarters` quarter-turns, snap a photo, and log the event."""
    global camera_streaming_allowed
    quarters = clean_quarters(quarters)
    rotations = quarters * QUARTER_ROTATION

    with feed_lock:
        # Block the stream loop from touching the hardware, and give it time to let go.
        camera_streaming_allowed = False
        time.sleep(0.3)
        print(f"\n--- FEEDING: {quarters} quarter-turn(s) = {rotations} rotation(s) ---")
        try:
            # 1. Spin motor
            spin_feeder_motor(rotations=rotations)
            time.sleep(1)

            # 2. Capture a confirmation photo
            filename = f"feed_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
            filepath = os.path.join("photos", filename)
            frame = capture_single_frame()
            if frame:
                with open(filepath, "wb") as f:
                    f.write(frame)

            # 3. Log data
            readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("database.txt", "a") as f:
                f.write(f"{readable_time},{filename}\n")
        finally:
            # Release the camera lock only after all hardware work is done.
            camera_streaming_allowed = True

# --- BACKGROUND SCHEDULER ---
def scheduler_loop():
    """Fire scheduled feedings once per matching minute."""
    print("Scheduler thread started.")
    last_minute = None
    while True:
        now = datetime.now().strftime("%H:%M")
        if now != last_minute:
            for entry in load_schedule().get("entries", []):
                if entry.get("time") == now:
                    print(f"Scheduled feed triggered at {now}")
                    perform_feed(entry.get("quarters", 4))
            last_minute = now
        time.sleep(15)

# --- ROUTES ---

@app.route('/')
def index():
    logs = []
    if os.path.exists("database.txt"):
        with open("database.txt", "r") as f:
            for line in f.readlines():
                if "," in line:
                    timestamp, filename = line.strip().split(",")
                    logs.append({"time": timestamp, "image": filename})
    logs.reverse()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    schedule = sorted(load_schedule().get("entries", []), key=lambda e: e.get("time", ""))
    return render_template('index.html', current_time=current_time, logs=logs, schedule=schedule)

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/feed', methods=['POST'])
def feed():
    quarters = clean_quarters(request.form.get('quarters'), default=4)
    perform_feed(quarters)
    return redirect(url_for('index'))

@app.route('/schedule/add', methods=['POST'])
def schedule_add():
    entry_time = (request.form.get('time') or "").strip()
    quarters = clean_quarters(request.form.get('quarters'), default=4)

    # Basic HH:MM validation so garbage never reaches the scheduler.
    try:
        datetime.strptime(entry_time, "%H:%M")
    except ValueError:
        return redirect(url_for('index'))

    data = load_schedule()
    data["entries"].append({
        "id": str(int(time.time() * 1000)),
        "time": entry_time,
        "quarters": quarters,
    })
    save_schedule(data)
    return redirect(url_for('index'))

@app.route('/schedule/delete', methods=['POST'])
def schedule_delete():
    entry_id = request.form.get('id')
    data = load_schedule()
    data["entries"] = [e for e in data["entries"] if e.get("id") != entry_id]
    save_schedule(data)
    return redirect(url_for('index'))

@app.route('/photos/<filename>')
def get_photo(filename):
    return send_from_directory('photos', filename)

if __name__ == '__main__':
    os.makedirs("photos", exist_ok=True)
    if not os.path.exists(SCHEDULE_FILE):
        save_schedule({"entries": []})
    # Start the scheduler in the background before the web server takes over.
    threading.Thread(target=scheduler_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
