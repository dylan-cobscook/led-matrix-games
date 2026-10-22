// The grid matches the physical LED matrix: 64 columns by 32 rows.
const columns = 64;
const rows = 32;
const canvas = document.getElementById("grid");
const context = canvas.getContext("2d");
const colorPicker = document.getElementById("pixel-color");
const nameDialog = document.getElementById("name-dialog");
const nameForm = document.getElementById("name-form");
const nameInput = document.getElementById("user-name");
const nameCookie = "pixel_drawer_name";
const savedNameCookie = document.cookie
  .split(";")
  .map((cookie) => cookie.trim())
  .find((cookie) => cookie.startsWith(`${nameCookie}=`));
let userName = savedNameCookie
  ? decodeURIComponent(savedNameCookie.slice(nameCookie.length + 1))
  : "Anonymous";
// Store only lit cells, using "x,y" as the key and a color as the value.
const litPixels = new Map();
// Null means this browser has not yet loaded an initial snapshot.
let pixelVersion = null;

if (!savedNameCookie || !userName.trim()) {
  userName = "Anonymous";
  nameDialog.addEventListener("cancel", (event) => event.preventDefault());
  nameInput.addEventListener("input", () => nameInput.setCustomValidity(""));
  nameForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const enteredName = nameInput.value.trim();
    if (!enteredName) {
      nameInput.setCustomValidity("Please enter your name.");
      nameInput.reportValidity();
      return;
    }
    userName = enteredName;
    document.cookie = `${nameCookie}=${encodeURIComponent(userName)}; Max-Age=31536000; Path=/; SameSite=Lax`;
    nameDialog.close();
  });
  nameDialog.showModal();
}

// Paint the background, colored cells, and grid lines onto the canvas.
function drawGrid() {
  // Scale the drawing for sharp lines on high-resolution screens.
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.fillStyle = "#111";
  context.fillRect(0, 0, width, height);

  const cellWidth = width / columns;
  const cellHeight = height / rows;
  // Convert each saved cell's grid position into its on-screen position.
  for (const [pixel, color] of litPixels) {
    const [x, y] = pixel.split(",").map(Number);
    context.fillStyle = color;
    context.fillRect(x * cellWidth, y * cellHeight, cellWidth, cellHeight);
  }

  context.strokeStyle = "#666";
  context.lineWidth = 1;
  context.beginPath();
  for (let x = 0; x <= columns; x++) {
    const lineX = Math.round(x * cellWidth) + 0.5;
    context.moveTo(lineX, 0);
    context.lineTo(lineX, height);
  }
  for (let y = 0; y <= rows; y++) {
    const lineY = Math.round(y * cellHeight) + 0.5;
    context.moveTo(0, lineY);
    context.lineTo(width, lineY);
  }
  context.stroke();
}

// Ask the device for its current pixels so changes on the matrix appear here.
async function syncPixels() {
  try {
    // Start with a snapshot, then ask for only changes newer than our version.
    const path = pixelVersion === null
      ? "/updates"
      : `/updates?since=${pixelVersion}`;
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Could not load matrix pixels: ${response.status}`);
    }

    const update = await response.text();
    const headerEnd = update.indexOf("\n");
    const [mode, versionText] = update.slice(0, headerEnd).split(":");
    const version = Number(versionText);
    if (
      headerEnd === -1
      || !Number.isSafeInteger(version)
      || version < 0
      || (mode !== "full" && mode !== "delta")
    ) {
      throw new Error("Received an invalid matrix pixel update");
    }

    const payload = update.slice(headerEnd + 1);
    let redraw = false;
    if (mode === "full") {
      // Fetch rows separately to keep each response small for the device.
      if (payload) {
        throw new Error("Received an invalid matrix pixel snapshot");
      }
      const snapshotPixels = new Map();
      for (let y = 0; y < rows; y++) {
        const rowResponse = await fetch(`/pixel-row?y=${y}`, {
          cache: "no-store"
        });
        if (!rowResponse.ok) {
          throw new Error(`Could not load matrix pixel row: ${rowResponse.status}`);
        }
        const row = await rowResponse.text();
        if (row.length !== columns * 6) {
          throw new Error("Received an invalid matrix pixel row");
        }
        for (let x = 0; x < columns; x++) {
          const color = row.slice(x * 6, (x + 1) * 6);
          if (color !== "------") {
            if (!/^[0-9a-f]{6}$/i.test(color)) {
              throw new Error("Received an invalid matrix pixel color");
            }
            snapshotPixels.set(`${x},${y}`, `#${color}`);
          }
        }
      }
      litPixels.clear();
      for (const [pixel, color] of snapshotPixels) {
        litPixels.set(pixel, color);
      }
      redraw = true;
    } else if (payload) {
      for (const line of payload.trimEnd().split("\n")) {
        const [xText, yText, color] = line.split(",");
        const x = Number(xText);
        const y = Number(yText);
        if (
          !Number.isInteger(x)
          || x < 0
          || x >= columns
          || !Number.isInteger(y)
          || y < 0
          || y >= rows
          || !/^[0-9a-f]{6}$/.test(color)
        ) {
          throw new Error("Received an invalid matrix pixel change");
        }
        litPixels.set(`${x},${y}`, `#${color}`);
      }
      redraw = true;
    }
    if (redraw) {
      drawGrid();
    }
    // Accept this version only after its payload has been applied successfully.
    pixelVersion = version;
  } catch (error) {
    console.error("Could not sync matrix pixels:", error);
  } finally {
    // A little timing variation prevents all connected browsers polling together.
    window.setTimeout(syncPixels, 500 + Math.random() * 250);
  }
}

// Convert a click's screen position to a grid cell and send it to the device.
canvas.addEventListener("pointerdown", async (event) => {
  const bounds = canvas.getBoundingClientRect();
  const x = Math.floor((event.clientX - bounds.left) / bounds.width * columns);
  const y = Math.floor((event.clientY - bounds.top) / bounds.height * rows);
  if (x < 0 || x >= columns || y < 0 || y >= rows) return;
  const color = colorPicker.value;

  // POST sends the selected cell and color to the device's /pixel handler.
  const response = await fetch("/pixel", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `x=${x}&y=${y}&color=${color.slice(1)}&name=${encodeURIComponent(userName)}`
  });
  if (!response.ok) {
    console.error("Could not light matrix pixel:", response.status);
    return;
  }
  litPixels.set(`${x},${y}`, color);
  drawGrid();
});

// Redraw to fit the screen when its size changes; then draw and sync initially.
window.addEventListener("resize", drawGrid);
drawGrid();
syncPixels();
