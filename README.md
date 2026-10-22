# Cobscook Tech Club LED Matrix Game

This is built in Circuit Python, HTML and Javascript to run on an Adafruit Matrix Portal M4 with a 64x32 RGB LED matrix.

The chip connects to Wi-Fi using the ESP32 co-processor, and serves a webpage where users can draw collaboratively pixel-by-pixel. As you draw, your screen will update with what's shown on the LED matrix, along with everyone else's pixels.

Drawings can be saved and recalled on the Admin page. Drawings are saved every 30 seconds by default, and the matrix will recall the last drawing that was displayed on power up.

## Development

In order to develop for this platform, you can clone the repo and open it in VS Code. If you install the Serial Monitor plugin, you can monitor the connected M4 while it's running, which shows useful diagnostic information and will print each pixel as it's drawn including color, coordinates, and the username and IP address of the person who drew it.

Wi-Fi information and admin password can be set in secrets.py. A sample is provided in the repo.

In order to update the code on the Matrix Portal, you must tell it to make the filesystem readable to the computer. In Serial Monitor, set Line Ending to CR, and send Ctrl+C. Then type:
`import storage`
`storage.remount("/", readonly=True)`

You should then see the CIRCUITPY drive is writable. Replace any files you update on the drive to update the device.

