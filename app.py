import os
import time
import json
import signal
import threading
from datetime import datetime, timedelta
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
LOG_FILE = "database.txt"
# Feed clips (and their log lines) older than this many days are deleted automatically.
RETENTION_DAYS = 30
# One motor "quarter" = a quarter of a full physical rotation.
QUARTER_ROTATION = 0.25
# Serialize hardware access so a manual feed and a scheduled feed never overlap.
feed_lock = threading.Lock()

# --- FEED CLIP (GIF) CONFIG ---
PRE_ROLL_SECONDS = 1.0     # keep filming this long BEFORE the motor starts
POST_ROLL_SECONDS = 3.0    # keep filming this long AFTER the motor stops
VIDEO_WIDTH = 640          # capture resolution (kept modest for the Pi Zero)
VIDEO_HEIGHT = 480
VIDEO_FPS = 15             # capture frame rate
GIF_FPS = 12               # GIF frame rate — smooth enough to read in the browser
GIF_WIDTH = 400            # GIF is scaled to this width (height auto) to stay light

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

# --- FEED HISTORY (plain text log + clip files) ---
def read_logs():
    """Return feed events in chronological order: [{'time','image','date'}]."""
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if "," not in line:
                    continue
                timestamp, filename = line.split(",", 1)
                logs.append({
                    "time": timestamp,
                    "image": filename,
                    "date": timestamp.split(" ")[0],  # "YYYY-MM-DD"
                })
    return logs

def prune_old_history():
    """Delete log lines and clip files older than RETENTION_DAYS."""
    if not os.path.exists(LOG_FILE):
        return
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    kept_lines = []
    removed_files = []
    with open(LOG_FILE, "r") as f:
        for line in f:
            stripped = line.strip()
            if "," not in stripped:
                continue
            timestamp, filename = stripped.split(",", 1)
            try:
                when = datetime.strptime(timestamp.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                kept_lines.append(stripped)  # keep anything we can't parse
                continue
            if when >= cutoff:
                kept_lines.append(stripped)
            else:
                removed_files.append(filename.strip())

    if not removed_files:
        return

    with open(LOG_FILE, "w") as f:
        for line in kept_lines:
            f.write(line + "\n")

    for filename in removed_files:
        path = os.path.join("photos", filename)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            print(f"Could not remove {path}: {e}")

    print(f"Pruned {len(removed_files)} feed clip(s) older than {RETENTION_DAYS} days.")

# --- FEED CLIP RECORDING ---
def record_feed_gif(quarters, gif_path):
    """
    Record a short clip that starts before the motor spins and ends
    POST_ROLL_SECONDS after it stops, then save it as an animated GIF.

    The motor spin happens *inside* the recording window, so the clip
    captures the food actually dropping.
    """
    rotations = quarters * QUARTER_ROTATION
    h264_path = gif_path[:-4] + ".h264"  # gif_path ends in ".gif"

    # Start the recorder running open-ended (-t 0); we stop it ourselves so the
    # clip length tracks the real motor time instead of a guessed duration.
    record_cmd = [
        "rpicam-vid",
        "-t", "0",
        "--width", str(VIDEO_WIDTH),
        "--height", str(VIDEO_HEIGHT),
        "--framerate", str(VIDEO_FPS),
        "--codec", "h264",
        "--nopreview",
        "-o", h264_path,
    ]
    proc = subprocess.Popen(record_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(PRE_ROLL_SECONDS)          # a moment before the food drops
        spin_feeder_motor(rotations=rotations)
        time.sleep(POST_ROLL_SECONDS)         # keep filming after the motor stops
    finally:
        # SIGINT lets rpicam-vid finalize the H.264 file cleanly.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # Convert the raw H.264 into a web-friendly animated GIF (palette pass for
    # good color at small size).
    convert_cmd = [
        "ffmpeg", "-y",
        "-r", str(VIDEO_FPS),
        "-i", h264_path,
        "-vf", (f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,"
                "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"),
        gif_path,
    ]
    try:
        subprocess.run(convert_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except Exception as e:
        print(f"GIF conversion error: {e}")
    finally:
        if os.path.exists(h264_path):
            os.remove(h264_path)

    return os.path.exists(gif_path)

# --- CORE FEED ACTION (shared by manual button and scheduler) ---
def perform_feed(quarters=4):
    """Record a feed clip while spinning the motor by `quarters` quarter-turns, then log it."""
    global camera_streaming_allowed
    quarters = clean_quarters(quarters)

    with feed_lock:
        # Block the stream loop from touching the hardware, and give it time to let go.
        camera_streaming_allowed = False
        time.sleep(0.3)
        print(f"\n--- FEEDING: {quarters} quarter-turn(s) = {quarters * QUARTER_ROTATION} rotation(s) ---")
        try:
            # Record the clip (this is what spins the motor) and save it as a GIF.
            filename = f"feed_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.gif"
            filepath = os.path.join("photos", filename)
            if not record_feed_gif(quarters, filepath):
                print("Warning: GIF was not produced.")

            # Log the event (the log/thumbnails render the GIF directly).
            readable_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_FILE, "a") as f:
                f.write(f"{readable_time},{filename}\n")
        finally:
            # Release the camera lock only after all hardware work is done.
            camera_streaming_allowed = True

# --- BACKGROUND SCHEDULER ---
def scheduler_loop():
    """Fire scheduled feedings once per matching minute, and prune history once a day."""
    print("Scheduler thread started.")
    last_minute = None
    last_prune_day = None
    while True:
        now_dt = datetime.now()
        today = now_dt.strftime("%Y-%m-%d")

        # Prune at startup and whenever the calendar day rolls over.
        if today != last_prune_day:
            prune_old_history()
            last_prune_day = today

        now = now_dt.strftime("%H:%M")
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
    all_logs = read_logs()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # The page shows a single day; default to today. Navigation jumps between
    # days that actually have feeds, so you never page through empty days.
    day = request.args.get('day', today_str)
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        day = today_str

    days_with_entries = sorted({log["date"] for log in all_logs}, reverse=True)
    day_logs = [log for log in all_logs if log["date"] == day]
    day_logs.reverse()  # newest feed first within the day

    older = [d for d in days_with_entries if d < day]   # desc order
    newer = [d for d in days_with_entries if d > day]
    prev_day = older[0] if older else None    # nearest older day with feeds
    next_day = newer[-1] if newer else None   # nearest newer day with feeds

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    schedule = sorted(load_schedule().get("entries", []), key=lambda e: e.get("time", ""))
    return render_template(
        'index.html',
        current_time=current_time,
        logs=day_logs,
        schedule=schedule,
        viewed_day=day,
        is_today=(day == today_str),
        prev_day=prev_day,
        next_day=next_day,
    )

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
