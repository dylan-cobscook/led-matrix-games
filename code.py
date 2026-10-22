# Standard library modules used for delays and the Wi-Fi credentials.
import gc
import json
import os
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
from adafruit_httpserver import (
    GET,
    POST,
    ChunkedResponse,
    FileResponse,
    Response,
    Route,
    Server,
)

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
DRAWINGS_DIRECTORY = "/drawings"
AUTOSAVE_PATH = DRAWINGS_DIRECTORY + "/current.json"
AUTOSAVE_DELAY = 30
# Keep a bounded change log so clients can catch up without storing every edit.
PIXEL_UPDATE_HISTORY = 64
# Each change gets a version so browsers can ask only for edits they have not seen.
pixel_version = 0
pixel_updates = []
drawing_dirty = False
last_drawing_change = 0
drawing_storage_available = False


def get_pixel_row(y):
    # Encode each cell as six hex characters, or dashes when the cell is dark.
    return "".join(
        "------"
        if pixels[x, y] == 0
        else "%06x" % palette[pixels[x, y]]
        for x in range(64)
    )


def get_pixel_chunk(y, start_x):
    return "".join(
        "------"
        if pixels[x, y] == 0
        else "%06x" % palette[pixels[x, y]]
        for x in range(start_x, start_x + 8)
    )


def ensure_drawings_directory():
    if DRAWINGS_DIRECTORY[1:] not in os.listdir("/"):
        os.mkdir(DRAWINGS_DIRECTORY)


def write_drawing(path, name):
    gc.collect()
    with open(path, "w") as drawing_file:
        drawing_file.write("LMG1\n")
        json.dump(name, drawing_file)
        drawing_file.write("\n")
        for y in range(32):
            for start_x in range(0, 64, 8):
                drawing_file.write(get_pixel_chunk(y, start_x))
                drawing_file.write("\n")
            gc.collect()


def skip_legacy_drawing_header(drawing_file):
    marker = ', "pixels": "'
    header = ""
    while len(header) < 256:
        character = drawing_file.read(1)
        if not character:
            break
        header += character
        if header.endswith(marker):
            name_data = header[: -len(marker)] + "}"
            name = json.loads(name_data)["name"]
            if not isinstance(name, str):
                raise ValueError("Invalid saved drawing name")
            return name
    raise ValueError("Invalid saved drawing header")


def skip_drawing_metadata(drawing_file):
    if drawing_file.read(5) != "LMG1\n":
        drawing_file.seek(0)
        return skip_legacy_drawing_header(drawing_file), False
    drawing_file.seek(0)
    drawing_file.readline()
    name = json.loads(drawing_file.readline())
    if not isinstance(name, str):
        raise ValueError("Invalid saved drawing name")
    return name, True


def read_drawing_name(path):
    with open(path, "r") as drawing_file:
        name, _ = skip_drawing_metadata(drawing_file)
    if not isinstance(name, str):
        raise ValueError("Invalid saved drawing name")
    return name


def read_drawing_pixels(path):
    global next_color_index
    gc.collect()
    with open(path, "r") as drawing_file:
        name, has_chunk_newlines = skip_drawing_metadata(drawing_file)
        drawing_colors = set()
        for chunk_number in range(32 * 8):
            chunk = drawing_file.read(48)
            if len(chunk) != 48:
                raise ValueError("Invalid saved drawing pixels")
            if has_chunk_newlines and drawing_file.readline() != "\n":
                raise ValueError("Invalid saved drawing pixels")
            for offset in range(0, 48, 6):
                color = chunk[offset : offset + 6]
                if color != "------":
                    if any(
                        character not in "0123456789abcdefABCDEF"
                        for character in color
                    ):
                        raise ValueError("Invalid saved drawing color")
                    drawing_colors.add(int(color, 16))
                    if len(drawing_colors) > 255:
                        raise ValueError("Saved drawing has too many colors")
            if chunk_number % 8 == 7:
                gc.collect()
        trailer = drawing_file.read(2 if not has_chunk_newlines else 1)
        if trailer != ('"}' if not has_chunk_newlines else ""):
            raise ValueError("Invalid saved drawing length")
        if drawing_file.read(1):
            raise ValueError("Invalid saved drawing length")

    gc.collect()
    color_indices.clear()
    next_color_index = 1
    palette[0] = 0x000000
    with open(path, "r") as drawing_file:
        _, has_chunk_newlines = skip_drawing_metadata(drawing_file)
        for y in range(32):
            for chunk_number in range(8):
                chunk = drawing_file.read(48)
                if has_chunk_newlines:
                    drawing_file.readline()
                start_x = chunk_number * 8
                for pixel_number in range(8):
                    color_text = chunk[pixel_number * 6 : pixel_number * 6 + 6]
                    x = start_x + pixel_number
                    if color_text == "------":
                        pixels[x, y] = 0
                    else:
                        color = int(color_text, 16)
                        color_index = color_indices.get(color)
                        if color_index is None:
                            color_index = next_color_index
                            color_indices[color] = color_index
                            palette[color_index] = color
                            next_color_index += 1
                        pixels[x, y] = color_index
            gc.collect()
    record_drawing_replaced()
    return name


def stream_drawing_pixels(path):
    with open(path, "r") as drawing_file:
        _, has_chunk_newlines = skip_drawing_metadata(drawing_file)
        for _ in range(32 * 8):
            yield drawing_file.read(48)
            if has_chunk_newlines:
                drawing_file.readline()


def record_pixel_change(x, y, color):
    global pixel_version
    pixel_version += 1
    pixel_updates.append((pixel_version, x, y, color))
    if len(pixel_updates) > PIXEL_UPDATE_HISTORY:
        del pixel_updates[0]


def record_drawing_replaced():
    global pixel_version
    pixel_version += PIXEL_UPDATE_HISTORY + 2
    pixel_updates.clear()
    pixel_updates.append((pixel_version, 0, 0, None))


def has_lit_pixels():
    for y in range(32):
        for x in range(64):
            if pixels[x, y] != 0:
                return True
    return False


def clear_drawing():
    global next_color_index
    had_pixels = has_lit_pixels()
    for y in range(32):
        for x in range(64):
            pixels[x, y] = 0
    color_indices.clear()
    next_color_index = 1
    palette[0] = 0x000000
    if had_pixels:
        record_drawing_replaced()


def load_autosave():
    global drawing_storage_available
    ensure_drawings_directory()
    drawing_storage_available = True
    if "current.json" in os.listdir(DRAWINGS_DIRECTORY):
        read_drawing_pixels(AUTOSAVE_PATH)


def initialize_drawing_storage():
    try:
        load_autosave()
    except (OSError, ValueError) as exc:
        print(
            "Drawing storage is unavailable; continuing without persistence:",
            exc,
        )


def save_autosave():
    write_drawing(AUTOSAVE_PATH, "Current drawing")


def save_autosave_if_due():
    global drawing_dirty, drawing_storage_available
    if (
        drawing_storage_available
        and drawing_dirty
        and time.monotonic() - last_drawing_change >= AUTOSAVE_DELAY
    ):
        try:
            save_autosave()
        except OSError as exc:
            print("Could not autosave drawing:", exc)
            drawing_storage_available = False
            return
        drawing_dirty = False
        print("Autosaved current drawing.")


def get_next_drawing_id():
    existing_files = os.listdir(DRAWINGS_DIRECTORY)
    number = 1
    while "drawing-%d.json" % number in existing_files:
        number += 1
    return "drawing-%d" % number


def save_named_drawing(name):
    drawing_id = get_next_drawing_id()
    write_drawing(DRAWINGS_DIRECTORY + "/" + drawing_id + ".json", name)
    return drawing_id


def list_drawings():
    drawings = []
    for filename in os.listdir(DRAWINGS_DIRECTORY):
        if filename.startswith("drawing-") and filename.endswith(".json"):
            drawing_id = filename[:-5]
            drawings.append(
                {
                    "id": drawing_id,
                    "name": read_drawing_name(
                        DRAWINGS_DIRECTORY + "/" + filename
                    ),
                }
            )
    drawings.sort(key=lambda drawing: drawing["id"])
    return drawings


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
    return FileResponse(
        request,
        filename="index.html",
        root_path="/",
        content_type="text/html; charset=utf-8",
    )


# Serve the browser code separately to keep each response small for the device.
def handle_app_js(request):
    return FileResponse(
        request,
        filename="app.js",
        root_path="/",
        content_type="application/javascript; charset=utf-8",
    )


def handle_admin_page(request):
    return FileResponse(
        request,
        filename="admin.html",
        root_path="/",
        content_type="text/html; charset=utf-8",
    )


def handle_admin(request):
    global drawing_dirty, last_drawing_change
    try:
        form = request.form_data
        password = form["password"]
        action = form["action"]
        if not isinstance(password, str) or not isinstance(action, str):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return make_response(
            request,
            "Invalid admin request",
            (400, "Bad Request"),
        )
    gc.collect()
    if password != secrets.secrets["admin_password"]:
        return make_response(
            request,
            "Incorrect admin password",
            (401, "Unauthorized"),
        )
    if not drawing_storage_available:
        return make_response(
            request,
            "Drawing storage is unavailable; check boot.py and filesystem access",
            (503, "Service Unavailable"),
        )

    try:
        if action == "list":
            return Response(
                request,
                json.dumps(list_drawings()),
                headers={"Cache-Control": "no-store"},
                content_type="application/json",
            )
        if action == "show":
            drawing_id = form.get("id", "")
            if (
                not isinstance(drawing_id, str)
                or not drawing_id.startswith("drawing-")
                or not drawing_id[8:].isdigit()
            ):
                return make_response(
                    request,
                    "Invalid drawing ID",
                    (400, "Bad Request"),
                )
            drawing_path = (
                DRAWINGS_DIRECTORY + "/" + drawing_id + ".json"
            )
            read_drawing_name(drawing_path)
            return ChunkedResponse(
                request,
                lambda: stream_drawing_pixels(drawing_path),
                headers={"Cache-Control": "no-store"},
                content_type="text/plain",
            )
        if action == "save":
            name = form.get("name", "")
            if not isinstance(name, str):
                return make_response(
                    request,
                    "Invalid drawing name",
                    (400, "Bad Request"),
                )
            name = "".join(
                character
                for character in name
                if ord(character) >= 32 and ord(character) != 127
            ).strip()[:32]
            if not name:
                name = "Untitled drawing"
            save_named_drawing(name)
            save_autosave()
            drawing_dirty = False
            return make_response(request, "Drawing saved")
        if action == "load":
            drawing_id = form.get("id", "")
            if (
                not isinstance(drawing_id, str)
                or not drawing_id.startswith("drawing-")
                or not drawing_id[8:].isdigit()
            ):
                return make_response(
                    request,
                    "Invalid drawing ID",
                    (400, "Bad Request"),
                )
            read_drawing_pixels(
                DRAWINGS_DIRECTORY + "/" + drawing_id + ".json"
            )
            save_autosave()
            drawing_dirty = False
            return make_response(request, "Drawing recalled")
        if action == "new":
            if has_lit_pixels():
                save_named_drawing("Untitled drawing")
            clear_drawing()
            save_autosave()
            drawing_dirty = False
            return make_response(request, "Started a new drawing")
    except (OSError, ValueError) as exc:
        print("Admin drawing operation failed:", exc)
        return make_response(
            request,
            "Could not complete drawing operation",
            (500, "Internal Server Error"),
        )
    return make_response(
        request,
        "Unknown admin action",
        (400, "Bad Request"),
    )


# Apply a pixel edit submitted by the browser.
def handle_pixel(request):
    global drawing_dirty, last_drawing_change, next_color_index
    try:
        form = request.form_data
        x = int(form["x"])
        y = int(form["y"])
        color_text = form.get("color", "FFFFFF")
        mode = form.get("mode", "paint")
        name = form.get("name", "Anonymous")
        if not isinstance(name, str) or mode not in ("paint", "erase"):
            raise ValueError
        if len(color_text) != 6 or any(
            character not in "0123456789abcdefABCDEF"
            for character in color_text
        ):
            raise ValueError
        color = int(color_text, 16)
    except (KeyError, TypeError, ValueError):
        return make_response(
            request,
            "Invalid pixel coordinates, color, or mode",
            (400, "Bad Request"),
        )
    if not 0 <= x < 64 or not 0 <= y < 32:
        return make_response(
            request,
            "Pixel coordinates out of range",
            (400, "Bad Request"),
        )
    name = "".join(
        character
        for character in name
        if ord(character) >= 32 and ord(character) != 127
    ).strip()[:32]
    if not name:
        name = "Anonymous"
    previous_color_index = pixels[x, y]
    if mode == "erase":
        pixels[x, y] = 0
        update_color = None
    else:
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
        pixels[x, y] = color_index
        update_color = color
    if previous_color_index != pixels[x, y]:
        record_pixel_change(x, y, update_color)
        drawing_dirty = True
        last_drawing_change = time.monotonic()
    client_ip = request.client_address[0]
    if mode == "erase":
        print("%s at %s erased %dx%d" % (name, client_ip, x, y))
    else:
        print(
            "\033[38;2;%d;%d;%dm%s at %s drew %dx%d\033[0m"
            % (
                (color >> 16) & 0xFF,
                (color >> 8) & 0xFF,
                color & 0xFF,
                name,
                client_ip,
                x,
                y,
            )
        )
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


# Stream a full matrix snapshot a row at a time to keep memory use bounded.
def handle_pixel_snapshot(request):
    snapshot_version = pixel_version

    def body():
        yield "full:%d\n" % snapshot_version
        for y in range(32):
            yield get_pixel_row(y) + "\n"

    return ChunkedResponse(
        request,
        body,
        headers={"Cache-Control": "no-store"},
        content_type="text/plain",
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
        # Delta lines contain one changed pixel: x,y,color or dashes when cleared.
        updates = ["delta:%d\n" % pixel_version]
        for version, x, y, color in pixel_updates:
            if version > since:
                if color is None:
                    updates.append("%d,%d,------\n" % (x, y))
                else:
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
            Route("/app.js", GET, handle_app_js),
            Route("/admin", GET, handle_admin_page),
            Route("/admin", POST, handle_admin),
            Route("/pixel", POST, handle_pixel),
            Route("/pixel-row", GET, handle_pixel_row),
            Route("/pixels", GET, handle_pixel_row),
            Route("/snapshot", GET, handle_pixel_snapshot),
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
initialize_drawing_storage()
print("Connecting to WiFi...")
connect_to_wifi()
server = start_server()


# Keep checking for incoming browser requests. Briefly pause after socket errors.
while True:
    try:
        server.poll()
        save_autosave_if_due()
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
