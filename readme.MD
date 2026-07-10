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
