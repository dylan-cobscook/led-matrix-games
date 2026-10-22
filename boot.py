# Allow CircuitPython to write saved drawings to the CIRCUITPY filesystem.
# While the firmware is running, the computer sees the drive as read-only.
import storage

storage.remount("/", readonly=False)
