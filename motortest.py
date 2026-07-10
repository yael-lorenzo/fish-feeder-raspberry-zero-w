import gpiozero
import time

# Update these numbers to match your exact GPIO array
motor_pins = [gpiozero.OutputDevice(p) for p in [17, 18, 27, 22]] 

print("Turning ALL motor signals ON. Check your driver LEDs now!")
for pin in motor_pins:
    pin.on()

time.sleep(10) # Keeps them on for 10 seconds

for pin in motor_pins:
    pin.off()
print("Test complete.")
