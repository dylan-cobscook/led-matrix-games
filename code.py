# Standard library modules used for delays and the Wi-Fi credentials.
import time
import secrets

# CircuitPython libraries for the board, LED matrix, and ESP32 Wi-Fi adapter.
import board
import busio
import displayio
import framebufferio
import rgbmatrix
from digitalio import DigitalInOut
from adafruit_esp32spi import adafruit_esp32spi
from adafruit_esp32spi.socketpool import SocketPool
from adafruit_httpserver import GET, POST, Response, Route, Server

# These pins connect the ESP32 Wi-Fi module to the board.
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)

# Create the SPI connection used to communicate with the Wi-Fi module.
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

# Set up the physical 64-by-32 RGB matrix and its drawing buffer.
displayio.release_displays()
matrix = rgbmatrix.RGBMatrix(
    width=64,
    height=32,
    bit_depth=6,
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
display.root_group = group

PORT = 80
# Keep a bounded change log so clients can catch up without storing every edit.
PIXEL_UPDATE_HISTORY = 64
# Each change gets a version so browsers can ask only for edits they have not seen.
pixel_version = 0
pixel_updates = []


def get_pixel_row(y):
    # Encode each cell as six hex characters, or dashes when the cell is dark.
    return "".join(
        "------"
        if pixels[x, y] == 0
        else "%06x" % palette[pixels[x, y]]
        for x in range(64)
    )


# Return a plain-text response with the requested status and headers.
def make_response(request, body, status=(200, "OK"), headers=None):
    return Response(
        request,
        body,
        status=status,
        headers=headers,
        content_type="text/plain",
    )


# Serve the browser application from the device filesystem.
def handle_home(request):
    with open("index.html", "r") as html_file:
        html = html_file.read()
    return Response(
        request,
        html,
        content_type="text/html; charset=utf-8",
    )


# Apply a pixel edit submitted by the browser.
def handle_pixel(request):
    global next_color_index, pixel_version
    try:
        form = request.form_data
        x = int(form["x"])
        y = int(form["y"])
        color_text = form.get("color", "FFFFFF")
        if len(color_text) != 6 or any(
            character not in "0123456789abcdefABCDEF"
            for character in color_text
        ):
            raise ValueError
        color = int(color_text, 16)
    except (KeyError, TypeError, ValueError):
        return make_response(
            request,
            "Invalid pixel coordinates or color",
            (400, "Bad Request"),
        )
    if not 0 <= x < 64 or not 0 <= y < 32:
        return make_response(
            request,
            "Pixel coordinates out of range",
            (400, "Bad Request"),
        )
    color_index = color_indices.get(color)
    if color_index is None:
        if next_color_index >= 256:
            return make_response(
                request,
                "Color palette is full",
                (400, "Bad Request"),
            )
        color_index = next_color_index
        next_color_index += 1
        color_indices[color] = color_index
        palette[color_index] = color
    previous_color_index = pixels[x, y]
    pixels[x, y] = color_index
    if previous_color_index != color_index:
        # Log actual changes only; repeated clicks on the same color need no sync.
        pixel_version += 1
        pixel_updates.append((pixel_version, x, y, color))
        if len(pixel_updates) > PIXEL_UPDATE_HISTORY:
            # Older clients will receive a fresh snapshot if their changes expire.
            del pixel_updates[0]
    client_ip = request.client_address[0]
    print("%s drew %d/%d #%06X" % (client_ip, x, y, color))
    return make_response(request, "OK")


# Send one row at a time so snapshot responses stay small on the device.
def handle_pixel_row(request):
    query = request.query_params
    try:
        if query.fields != ["y"] or len(query.get_list("y")) != 1:
            raise ValueError
        y = int(query["y"])
    except (KeyError, TypeError, ValueError):
        return make_response(
            request,
            "Invalid pixel row",
            (400, "Bad Request"),
        )
    if not 0 <= y < 32:
        return make_response(
            request,
            "Pixel row out of range",
            (400, "Bad Request"),
        )
    return make_response(
        request,
        get_pixel_row(y),
        headers={"Cache-Control": "no-store"},
    )


# Return only pixel changes since the client's last update version.
def handle_updates(request):
    query = request.query_params
    since = None
    if query.fields:
        try:
            if query.fields != ["since"] or len(query.get_list("since")) != 1:
                raise ValueError
            since = int(query["since"])
            if since < 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return make_response(
                request,
                "Invalid update version",
                (400, "Bad Request"),
            )

    # Send a full snapshot to new or stale clients so they can resynchronize.
    needs_snapshot = (
        since is None
        or since > pixel_version
        or (
            pixel_updates
            and since < pixel_updates[0][0] - 1
        )
    )
    if needs_snapshot:
        # The browser fetches each row separately to limit peak memory use.
        body = "full:%d\n" % pixel_version
    else:
        # Delta lines contain one changed pixel each: x,y,six-digit-color.
        updates = ["delta:%d\n" % pixel_version]
        for version, x, y, color in pixel_updates:
            if version > since:
                updates.append("%d,%d,%06x\n" % (x, y, color))
        body = "".join(updates)

    return make_response(
        request,
        body,
        headers={"Cache-Control": "no-store"},
    )


def create_server():
    # Use ESP32SPI's socket pool with Adafruit's maintained HTTP server.
    new_server = Server(SocketPool(esp))
    new_server.add_routes(
        [
            Route("/", GET, handle_home),
            Route("/pixel", POST, handle_pixel),
            Route("/pixel-row", GET, handle_pixel_row),
            Route("/pixels", GET, handle_pixel_row),
            Route("/updates", GET, handle_updates),
        ]
    )
    return new_server


def connect_to_wifi():
    # Keep retrying until the ESP32 has joined the configured network.
    while True:
        try:
            if not esp.is_connected:
                esp.connect_AP(
                    secrets.secrets["ssid"], secrets.secrets["password"]
                )
            if esp.is_connected:
                return
        except (OSError, RuntimeError) as exc:
            if "ESP32 not responding" in str(exc):
                print("ESP32 is not responding; resetting it...")
                esp.reset()
            else:
                print("WiFi connection error:", exc)
        time.sleep(1)


def start_server():
    # Create a fresh server after resets so it does not reuse stale sockets.
    while True:
        try:
            new_server = create_server()
            new_server.start(esp.pretty_ip(esp.ip_address), PORT)
            print(
                "Listening for web requests at http://%s:%d/"
                % (esp.pretty_ip(esp.ip_address), PORT)
            )
            return new_server
        except (OSError, RuntimeError) as exc:
            if "ESP32 not responding" not in str(exc):
                raise
            print("ESP32 stopped responding while starting the server.")
            esp.reset()
            connect_to_wifi()


def recover_esp32():
    # Reset the co-processor, reconnect Wi-Fi, and replace its lost sockets.
    print("ESP32 is not responding; resetting and reconnecting...")
    esp.reset()
    connect_to_wifi()
    return start_server()


# Connect to Wi-Fi and start serving requests.
print("Connecting to WiFi...")
connect_to_wifi()
server = start_server()


# Keep checking for incoming browser requests. Briefly pause after socket errors.
while True:
    try:
        server.poll()
    except OSError as exc:
        if "ESP32 not responding" in str(exc):
            server = recover_esp32()
        else:
            print("Socket error:", exc)
            time.sleep(1)
    except RuntimeError as exc:
        if "ESP32 not responding" in str(exc):
            server = recover_esp32()
        elif str(exc).startswith("Failed to send "):
            print("Socket send error:", exc)
            time.sleep(1)
        else:
            raise
