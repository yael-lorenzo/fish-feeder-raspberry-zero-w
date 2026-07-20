## Hardware Wiring & Pin Mapping

The system utilizes a Raspberry Pi Zero connected to a 28BYJ-48 stepper motor via a ULN2003 driver board, along with an external activity status LED.

### Pin Connection Reference Table

| Component | Component Pin | Raspberry Pi Pin (Physical) | Raspberry Pi GPIO (BCM) | Notes / Function |
| :--- | :--- | :--- | :--- | :--- |
| **ULN2003 Driver** | IN1 | Pin 11 | GPIO 17 | Motor Phase A |
| **ULN2003 Driver** | IN2 | Pin 12 | GPIO 18 | Motor Phase B |
| **ULN2003 Driver** | IN3 | Pin 13 | GPIO 27 | Motor Phase C |
| **ULN2003 Driver** | IN4 | Pin 15 | GPIO 22 | Motor Phase D |
| **ULN2003 Driver** | VCC | Pin 2 or 4 | 5V Power | Main power for motor driver |
| **ULN2003 Driver** | GND | Pin 6 (or any GND) | Ground | Common ground connection |
| **External LED** | Long Leg (+) | Pin 40 | GPIO 21 | Requires 330Ω resistor in series |
| **External LED** | Short Leg (-) | Pin 39 (or any GND) | Ground | Cathode return path |

---

### Important Wiring Notes

* **Common Ground:** Ensure that the ULN2003 driver board, the external status LED, and the Raspberry Pi all share a common ground (`GND`) plane to avoid signal drops or driver floating.
* **LED Current Limiting:** Always place a **220Ω to 470Ω resistor** (330Ω recommended) in series with the positive (long) leg of the status LED before connecting it to Pin 40 to protect the Pi's internal GPIO circuitry.
* **Python Initialization Array:** In the software configuration (`app.py`), the motor pin definition array maps directly to the BCM numbers:
  ```python
  motor_pins = [gpiozero.OutputDevice(p) for p in [17, 18, 27, 22]]

### Tailscale Remote Access

To access the fish feeder interface securely from outside the local home network without opening public router ports or running the Flask application as root, the system utilizes **Tailscale** and its secure reverse proxy capabilities.

#### 1. Installation
Install Tailscale on the Raspberry Pi by running the official setup script:
```bash
curl -fsSL [https://tailscale.com/install.sh](https://tailscale.com/install.sh) | sh

Once installed, authenticate the machine to your Tailnet by running:

```bash
sudo tailscale up

#### 2. Exposing the Flask App Safely
Because the Flask application runs on port 5000 under an unprivileged user account for security reasons, Tailscale handles the secure HTTPS port 443 binding and forwards the traffic internally.

Run the background proxy routing command:

```bash
tailscale serve --bg [http://127.0.0.1:5000](http://127.0.0.1:5000)
Verify that the proxy configuration is active and fetch your unique .ts.net address by running:

```bash
tailscale serve status
#### 3. Accessing the Application
Your private global URL will look like:
https://fish-feeder.mammut-saturation.ts.net

⚠️ CRITICAL NOTE ON USAGE:
Because .ts.net domains are part of a secure, private network layer and are not exposed to the public internet, the Tailscale client application must be explicitly turned ON and connected on the device you are browsing from (e.g., your smartphone or laptop).

If the Tailscale client app is turned off on your device, the domain will fail to resolve and will result in a DNS_PROBE_FINISHED_NXDOMAIN error.
