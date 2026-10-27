import base64
import io
from pathlib import Path

import numpy as np
from flask import Flask, render_template, request
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from palette import accessible_pairs, extract_palette

BASE_DIR = Path(__file__).parent
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "heic", "heif"}
PREVIEW_SIZE = (1200, 1200)
DEFAULTS = {"n_colors": 10, "delta": 24, "reduce_gradient": True, "reduce_brightness": True}

# фото з iPhone (HEIC) — Pillow сам їх не читає
register_heif_opener()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


class UploadError(Exception):
    pass


@app.context_processor
def asset_version():
    # змінюється при кожній правці css/js, тож браузер не тримає старі стилі в кеші
    static = BASE_DIR / "static"
    return {"asset_v": int(max((static / f).stat().st_mtime for f in ("style.css", "app.js")))}


def to_int(value, default, low, high):
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def read_options(form):
    # незатиснутий чекбокс браузер не надсилає, тож його відсутність = False
    return {
        "n_colors": to_int(form.get("n_colors"), DEFAULTS["n_colors"], 1, 30),
        "delta": to_int(form.get("delta"), DEFAULTS["delta"], 1, 255),
        "reduce_gradient": "reduce_gradient" in form,
        "reduce_brightness": "reduce_brightness" in form,
    }


def load_image(file):
    if not file or not file.filename:
        raise UploadError("Please choose an image.")
    if file.filename.rsplit(".", 1)[-1].lower() not in ALLOWED_EXT:
        raise UploadError("Unsupported file type. Try PNG, JPG, WebP, HEIC, GIF or BMP.")
    try:
        image = Image.open(file.stream)
        image.load()
    except (UnidentifiedImageError, OSError):
        raise UploadError("This file is not a valid image.")
    return image


def to_data_url(img, fmt):
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def mask_data_url(labels, index):
    # напівпрозора «вуаль» поверх усього, крім пікселів цього кольору
    alpha = np.where(labels == index, 0, 185).astype(np.uint8)
    return to_data_url(Image.fromarray(alpha, mode="L").convert("LA"), "PNG")


def preview_data_url(image):
    # без JavaScript картинку не зберігаємо на диск — віддаємо зменшену копію прямо в html
    img = ImageOps.exif_transpose(image).convert("RGB")
    img.thumbnail(PREVIEW_SIZE)
    return to_data_url(img, "JPEG")


def build_result(image, options):
    colors, labels = extract_palette(image, **options)
    return {
        "palette": [(c, mask_data_url(labels, i)) for i, c in enumerate(colors)],
        "pairs": accessible_pairs(colors),
    }


@app.get("/")
def index():
    return render_template("index.html", **DEFAULTS)


@app.post("/")
def index_post():
    # запасний шлях без JavaScript: звичайна форма і повне перезавантаження сторінки
    options = read_options(request.form)
    try:
        image = load_image(request.files.get("image"))
    except UploadError as err:
        return render_template("index.html", error=str(err), **options), 400
    return render_template(
        "index.html",
        preview=preview_data_url(image),
        filename=request.files["image"].filename,
        **build_result(image, options),
        **options,
    )


@app.post("/palette")
def palette_fragment():
    # для JavaScript: лише блок з результатом, щоб оновлювати його без перезавантаження
    try:
        image = load_image(request.files.get("image"))
    except UploadError as err:
        return render_template("_result.html", error=str(err)), 400
    # браузер не вміє показати цей формат (напр. HEIC не в Safari) — превʼю робимо тут
    preview = preview_data_url(image) if "need_preview" in request.form else None
    return render_template("_result.html", preview=preview, **build_result(image, read_options(request.form)))


@app.errorhandler(413)
def too_large(_err):
    error = "The file is larger than 10 MB."
    if request.path == "/palette":
        return render_template("_result.html", error=error), 413
    return render_template("index.html", error=error, **DEFAULTS), 413


if __name__ == "__main__":
    app.run(debug=True)
