import os
import time
from datetime import datetime
import subprocess
from flask import Flask, render_template, Response, redirect, url_for, send_from_directory
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

def spin_feeder_motor(rotations=1):
    """
    Spins the 28BYJ-48 stepper motor using the working nested loop structure,
    calibrated precisely to hit 1.0 full turn.
    """
    print("Motor spinning started...")
    
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
    global camera_streaming_allowed
    camera_streaming_allowed = False
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
        camera_streaming_allowed = True
        return result.stdout
    except Exception as e:
        print(f"Camera capture error: {e}")
        camera_streaming_allowed = True
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
    return render_template('index.html', current_time=current_time, logs=logs)

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/feed', methods=['POST'])
def feed():
    global camera_streaming_allowed
    print("\n--- FEED ROUTE TRIGGERED ---")
    # 1. Spin motor
    spin_feeder_motor(rotations=1)
    time.sleep(1)
    
    # 2. Capture a high-res confirmation photo
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
        
    return redirect(url_for('index'))

@app.route('/photos/<filename>')
def get_photo(filename):
    return send_from_directory('photos', filename)

if __name__ == '__main__':
    os.makedirs("photos", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
