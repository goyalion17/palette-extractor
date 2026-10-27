const form = document.getElementById("studio");
const input = document.getElementById("image");
const drop = document.getElementById("drop");
const preview = document.getElementById("preview");
const veil = document.getElementById("veil");
const loupe = document.getElementById("loupe");
const result = document.getElementById("result");
const picked = document.getElementById("picked");
const filenameEl = document.getElementById("filename");
const toast = document.getElementById("toast");

let file = null;
// true, якщо браузер не зміг показати файл сам — тоді превʼю просимо в сервера
let needPreview = false;
let controller = null;
let debounce = null;
// копія фото в canvas — з неї піпетка читає колір пікселя
const sampler = document.createElement("canvas").getContext("2d", { willReadFrequently: true });

const isImage = (f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name);

const toHex = (r, g, b) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");

function showToast(text) {
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => (toast.hidden = true), 1600);
}

async function copy(text, label = text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`Copied ${label}`);
  } catch {
    showToast("Copy failed");
  }
}

/* ---------- завантаження ---------- */

function setFile(f) {
  if (!f) return;
  if (!isImage(f)) {
    showToast("Please choose an image file");
    return;
  }
  file = f;
  needPreview = false;
  if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
  preview.src = URL.createObjectURL(f);
  drop.classList.add("has-image");
  filenameEl.textContent = f.name;
  input.required = false;
  picked.hidden = true;
  refresh();
}

input.addEventListener("change", () => setFile(input.files[0]));
document.getElementById("replace").addEventListener("click", () => input.click());

drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("is-dragover");
});
drop.addEventListener("dragleave", () => drop.classList.remove("is-dragover"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("is-dragover");
  setFile(e.dataTransfer.files[0]);
});
// файл, кинутий повз зону, інакше браузер просто відкриє його
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
// вставка картинки з буфера обміну (Cmd+V)
document.addEventListener("paste", (e) => {
  const item = [...e.clipboardData.files].find(isImage);
  if (item) setFile(item);
});

/* ---------- перерахунок палітри ---------- */

async function refresh() {
  if (!file) return;
  // попередній запит уже неактуальний — скасовуємо, щоб старі дані не перезаписали нові
  controller?.abort();
  controller = new AbortController();
  const data = new FormData(form);
  data.set("image", file);
  if (needPreview) data.set("need_preview", "1");
  result.classList.add("is-loading");
  try {
    const resp = await fetch(form.dataset.paletteUrl, { method: "POST", body: data, signal: controller.signal });
    result.innerHTML = await resp.text();
    const serverPreview = result.querySelector(".server-preview");
    if (serverPreview) {
      needPreview = false;
      preview.src = serverPreview.dataset.src;
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    result.innerHTML = '<p class="error">Could not reach the server. Try again.</p>';
  }
  result.classList.remove("is-loading");
}

form.addEventListener("input", (e) => {
  if (e.target === input) return;
  if (e.target.dataset.output) document.getElementById(e.target.dataset.output).value = e.target.value;
  clearTimeout(debounce);
  debounce = setTimeout(refresh, 180);
});
form.addEventListener("submit", (e) => {
  e.preventDefault();
  refresh();
});

/* ---------- підсвітка кольору на фото ---------- */

function highlight(index) {
  const swatch = result.querySelector(`.swatch[data-index="${index}"]`);
  result.querySelectorAll(".is-active").forEach((el) => el.classList.remove("is-active"));
  result.querySelector(".strip")?.classList.toggle("has-active", Boolean(swatch));
  if (!swatch) {
    veil.classList.remove("is-visible");
    return;
  }
  result.querySelectorAll(`[data-index="${index}"]`).forEach((el) => el.classList.add("is-active"));
  const mask = `url("${swatch.dataset.mask}")`;
  veil.style.webkitMaskImage = mask;
  veil.style.maskImage = mask;
  veil.classList.add("is-visible");
}

const indexOf = (target) => target.closest?.("[data-index]")?.dataset.index;
result.addEventListener("pointerover", (e) => highlight(indexOf(e.target)));
result.addEventListener("pointerleave", () => highlight(null));
result.addEventListener("focusin", (e) => highlight(indexOf(e.target)));
result.addEventListener("focusout", () => highlight(null));

/* ---------- піпетка ---------- */

preview.addEventListener("error", () => {
  if (!file || !preview.src.startsWith("blob:")) return;
  needPreview = true;
  refresh();
});

preview.addEventListener("load", () => {
  const scale = Math.min(1, 1200 / Math.max(preview.naturalWidth, preview.naturalHeight));
  sampler.canvas.width = Math.round(preview.naturalWidth * scale);
  sampler.canvas.height = Math.round(preview.naturalHeight * scale);
  sampler.drawImage(preview, 0, 0, sampler.canvas.width, sampler.canvas.height);
});

function sample(e) {
  const rect = preview.getBoundingClientRect();
  const x = Math.min(sampler.canvas.width - 1, Math.floor(((e.clientX - rect.left) / rect.width) * sampler.canvas.width));
  const y = Math.min(sampler.canvas.height - 1, Math.floor(((e.clientY - rect.top) / rect.height) * sampler.canvas.height));
  const [r, g, b] = sampler.getImageData(x, y, 1, 1).data;
  return { hex: toHex(r, g, b), left: e.clientX - rect.left, top: e.clientY - rect.top };
}

preview.addEventListener("pointermove", (e) => {
  if (!sampler.canvas.width) return;
  const { hex, left, top } = sample(e);
  loupe.hidden = false;
  loupe.style.background = hex;
  loupe.style.left = `${left}px`;
  loupe.style.top = `${top}px`;
});
preview.addEventListener("pointerleave", () => (loupe.hidden = true));

drop.addEventListener("click", (e) => {
  if (!drop.classList.contains("has-image")) return;
  // інакше клік по фото (всередині label) знову відкриє вибір файлу
  e.preventDefault();
  if (e.target !== preview || !sampler.canvas.width) return;
  const { hex } = sample(e);
  picked.hidden = false;
  picked.querySelector(".picked-chip").style.background = hex;
  const code = picked.querySelector(".code");
  code.textContent = hex;
  code.dataset.copy = hex;
  copy(hex);
});

/* ---------- копіювання й експорт ---------- */

function readPalette() {
  return [...result.querySelectorAll(".swatch")].map((el) => ({
    hex: el.dataset.hex,
    rgb: el.dataset.rgb.split(",").map(Number),
    share: Number(el.dataset.share),
  }));
}

function downloadPng(colors) {
  const width = 1200;
  const height = 640;
  const ctx = document.createElement("canvas").getContext("2d");
  ctx.canvas.width = width;
  ctx.canvas.height = height;
  ctx.fillStyle = "#f5f2ec";
  ctx.fillRect(0, 0, width, height);
  const col = width / colors.length;
  colors.forEach((c, i) => {
    ctx.fillStyle = c.hex;
    ctx.fillRect(i * col, 0, Math.ceil(col), 520);
    ctx.fillStyle = "#1c1b19";
    ctx.font = `500 ${Math.min(22, col / 5)}px "JetBrains Mono", monospace`;
    ctx.fillText(c.hex.toUpperCase(), i * col + 12, 568);
    ctx.fillStyle = "#77726a";
    ctx.font = `${Math.min(16, col / 7)}px "JetBrains Mono", monospace`;
    ctx.fillText(`${(c.share * 100).toFixed(1)}%`, i * col + 12, 598);
  });
  ctx.canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "palette.png";
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

document.addEventListener("click", (e) => {
  const copyBtn = e.target.closest("[data-copy]");
  if (copyBtn?.dataset.copy) copy(copyBtn.dataset.copy);

  const exportBtn = e.target.closest("[data-export]");
  if (!exportBtn) return;
  const colors = readPalette();
  if (exportBtn.dataset.export === "css") {
    const vars = colors.map((c, i) => `  --palette-${i + 1}: ${c.hex};`).join("\n");
    copy(`:root {\n${vars}\n}`, "CSS variables");
  } else if (exportBtn.dataset.export === "json") {
    copy(JSON.stringify(colors, null, 2), "JSON");
  } else {
    downloadPng(colors);
  }
});
