import time
import secrets
import board
import busio
import displayio
import framebufferio
import rgbmatrix
from digitalio import DigitalInOut
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wsgiserver

esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)

spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

# Initialize the 64x32 RGB matrix.
displayio.release_displays()
matrix = rgbmatrix.RGBMatrix(
    width=64,
    height=32,
    bit_depth=1,
    rgb_pins=[
        board.MTX_R1,
        board.MTX_G1,
        board.MTX_B1,
        board.MTX_R2,
        board.MTX_G2,
        board.MTX_B2,
    ],
    addr_pins=[
        board.MTX_ADDRA,
        board.MTX_ADDRB,
        board.MTX_ADDRC,
        board.MTX_ADDRD,
    ],
    clock_pin=board.MTX_CLK,
    latch_pin=board.MTX_LAT,
    output_enable_pin=board.MTX_OE,
)
display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)
pixels = displayio.Bitmap(64, 32, 256)
palette = displayio.Palette(256)
palette[0] = 0x000000
palette[1] = 0xFFFFFF
color_indices = {0xFFFFFF: 1}
next_color_index = 2
group = displayio.Group()
group.append(displayio.TileGrid(pixels, pixel_shader=palette))
display.show(group)

# Connect to WiFi
print("Connecting to WiFi...")
while not esp.is_connected:
    try:
        esp.connect_AP(secrets.secrets["ssid"], secrets.secrets["password"])
    except RuntimeError:
        continue



PORT = 80


def web_app(environ, start_response):
    global next_color_index
    method = environ["REQUEST_METHOD"]
    path = environ["PATH_INFO"]

    if method == "POST" and path == "/pixel":
        try:
            form = {}
            for item in environ["wsgi.input"].read().split("&"):
                key, value = item.split("=", 1)
                form[key] = value
            x = int(form["x"])
            y = int(form["y"])
            color_text = form.get("color", "FFFFFF")
            if len(color_text) != 6 or any(
                character not in "0123456789abcdefABCDEF"
                for character in color_text
            ):
                raise ValueError
            color = int(color_text, 16)
        except (KeyError, ValueError):
            start_response("400 Bad Request", [("Content-Type", "text/plain")])
            return ["Invalid pixel coordinates or color"]
        if not 0 <= x < 64 or not 0 <= y < 32:
            start_response("400 Bad Request", [("Content-Type", "text/plain")])
            return ["Pixel coordinates out of range"]
        color_index = color_indices.get(color)
        if color_index is None:
            if next_color_index >= 256:
                start_response("400 Bad Request", [("Content-Type", "text/plain")])
                return ["Color palette is full"]
            color_index = next_color_index
            next_color_index += 1
            color_indices[color] = color_index
            palette[color_index] = color
        pixels[x, y] = color_index
        start_response("200 OK", [("Content-Type", "text/plain")])
        return ["OK"]

    if method == "GET" and path == "/":
        with open("index.html", "r") as html_file:
            html = html_file.read()
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [html]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return ["Not found"]


adafruit_esp32spi_wsgiserver.set_interface(esp)
server = adafruit_esp32spi_wsgiserver.WSGIServer(
    port=PORT, application=web_app
)
server.start()

print(
    "Listening for web requests at http://%s:%d/"
    % (esp.pretty_ip(esp.ip_address), PORT)
)

while True:
    try:
        server.update_poll()
    except OSError as exc:
        print("Socket error:", exc)
        time.sleep(1)
