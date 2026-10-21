import time
import secrets
import board
import busio
from digitalio import DigitalInOut
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi import adafruit_esp32spi_wsgiserver

esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)

spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

# Connect to WiFi
print("Connecting to WiFi...")
while not esp.is_connected:
    try:
        esp.connect_AP(secrets.secrets["ssid"], secrets.secrets["password"])
    except RuntimeError:
        continue



PORT = 80

def web_app(environ, start_response):
    print("Request:", environ["REQUEST_METHOD"], environ["PATH_INFO"])
    html = (
        "<!DOCTYPE html>"
        "<html><body>"
        "<h1>Hello, world!</h1>"
        "<p>Matrix Portal web server is running.</p>"
        "</body></html>"
    )
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [html]


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
