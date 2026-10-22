# Cobscook Tech Club LED Matrix Game

This is built in Circuit Python, HTML and Javascript to run on an Adafruit Matrix Portal M4 with a 64x32 RGB LED matrix.

The chip connects to Wi-Fi using the ESP32 co-processor, and serves a webpage where users can draw collaboratively pixel-by-pixel. As you draw, your screen will update with what's shown on the LED matrix, along with everyone else's pixels.

Everything is run locally on the Portal, local network and individual browsers with no cloud connection required.

Drawings can be saved and recalled on the Admin page. Drawings are saved every 30 seconds by default, and the matrix will recall the last drawing that was displayed on power up.

## Development

In order to develop for this platform, you can clone the repo and open it in VS Code. If you install the Serial Monitor plugin, you can monitor the connected M4 while it's running, which shows useful diagnostic information and will print each pixel as it's drawn including color, coordinates, and the username and IP address of the person who drew it.

Wi-Fi information and admin password can be set in secrets.py. A sample is provided in the repo.

In order to update the code on the Matrix Portal, you must tell it to make the filesystem readable to the computer. In VS Code Serial Monitor, set Line Ending to CR, and send Ctrl+C. When you get `>>>`, type these and hit send:

`import storage`

`storage.remount("/", readonly=True)`

You should then see the `CIRCUITPY` drive is writable. Replace any files you want to update on the drive to update the device.

`boot.py` is run when the device first boots, followed by `code.py`. We're only using `boot.py` to set the filesystem as writable on boot, then the main code is in `code.py`.

`index.html` is the page that loads when you vist the device's IP address. `admin.html` is the admin page, and `app.js` handles Javascript for the website.