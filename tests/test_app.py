import io

import numpy as np
import pytest
from PIL import Image

from app import app
from palette import Color, accessible_pairs, contrast_ratio, extract_palette

ALL_ON = {"reduce_gradient": "on", "reduce_brightness": "on"}


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def make_image():
    # 75% червоного і 25% синього — результат відомий наперед
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    img.paste((0, 0, 255), (0, 0, 50, 50))
    return img


def as_file(img, name="test.png"):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf, name


def hexes(colors):
    return [c.hex for c in colors]


def test_extract_palette_order_share_and_exact_hex():
    colors, _ = extract_palette(make_image())
    # HEX — справжній середній колір, а не центр кошика
    assert hexes(colors) == ["#ff0000", "#0000ff"]
    assert colors[0].share == pytest.approx(0.75)
    assert colors[1].share == pytest.approx(0.25)


def test_labels_map_pixels_to_palette():
    colors, labels = extract_palette(make_image())
    assert labels.shape == (100, 100)
    assert labels[0, 0] == 1  # синій кут
    assert labels[99, 99] == 0
    assert (labels == 0).mean() == pytest.approx(colors[0].share)


def test_transparent_pixels_are_ignored():
    colors, labels = extract_palette(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    assert colors == []
    assert (labels == -1).all()


def test_reduce_gradient_merges_neighbouring_shades():
    # два відтінки сірого в сусідніх кошиках (крок 24)
    img = Image.new("RGB", (100, 100), (100, 100, 100))
    img.paste((130, 130, 130), (0, 0, 40, 100))
    assert len(extract_palette(img, reduce_gradient=False, reduce_brightness=False)[0]) == 2
    colors, labels = extract_palette(img, reduce_gradient=True, reduce_brightness=False)
    # колір групи — її найчастіший відтінок, а частка — уся група
    assert hexes(colors) == ["#646464"]
    assert colors[0].share == pytest.approx(1.0)
    assert (labels == 0).all()


def test_reduce_brightness_merges_dark_and_light_versions():
    # червоний і вдвічі темніший червоний — не сусіди, тож gradient їх не зливає
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    img.paste((128, 0, 0), (0, 0, 30, 100))
    assert len(extract_palette(img, reduce_gradient=True, reduce_brightness=False)[0]) == 2
    colors, _ = extract_palette(img, reduce_gradient=False, reduce_brightness=True)
    assert hexes(colors) == ["#ff0000"]


def test_reduce_brightness_keeps_black_and_white_apart():
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    img.paste((0, 0, 0), (0, 0, 30, 100))
    colors, _ = extract_palette(img)
    assert hexes(colors) == ["#ffffff", "#000000"]


def test_reduce_brightness_keeps_gray_apart_from_colours():
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    img.paste((255, 0, 0), (0, 0, 50, 100))
    img.paste((128, 0, 0), (0, 0, 20, 100))
    colors, _ = extract_palette(img, reduce_gradient=False, reduce_brightness=True)
    shares = {c.hex: c.share for c in colors}
    assert set(shares) == {"#ff0000", "#808080"}
    assert shares["#ff0000"] == pytest.approx(0.5)


def test_noise_image_is_fast_enough():
    # найгірший випадок: десятки тисяч унікальних кольорів
    rng = np.random.default_rng(0)
    img = Image.fromarray(rng.integers(0, 256, (300, 300, 3), dtype=np.uint8))
    colors, _ = extract_palette(img, delta=1)
    assert len(colors) == 10


def test_color_formats():
    c = Color((255, 0, 0), 1.0)
    assert c.hex == "#ff0000"
    assert c.hsl == "hsl(0, 100%, 50%)"
    assert not Color((20, 30, 90), 1.0).is_light
    assert Color((250, 240, 200), 1.0).is_light


def test_contrast_and_accessible_pairs():
    black, white, gray = Color((0, 0, 0), 0.5), Color((255, 255, 255), 0.3), Color((128, 128, 128), 0.2)
    assert contrast_ratio(black, white) == pytest.approx(21)
    pairs = accessible_pairs([black, white, gray])
    assert pairs[0][:2] == (black, white)
    # сірий з білим (~3.9:1) не проходить AA
    assert all({a.hex, b.hex} != {"#808080", "#ffffff"} for a, b, _ in pairs)


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Drop an image here" in resp.data


def test_form_post_shows_full_page(client):
    resp = client.post("/", data={"image": as_file(make_image()), "n_colors": "5", **ALL_ON},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"<html" in resp.data
    assert b"#ff0000" in resp.data
    assert b"75.0%" in resp.data


def test_palette_fragment(client):
    resp = client.post("/palette", data={"image": as_file(make_image()), **ALL_ON},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"<html" not in resp.data
    assert resp.data.count(b'class="swatch"') == 2
    assert b"data:image/png;base64," in resp.data  # маски для підсвітки


def test_unchecked_options_are_off(client):
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    img.paste((128, 0, 0), (0, 0, 30, 100))
    resp = client.post("/palette", data={"image": as_file(img)}, content_type="multipart/form-data")
    assert b"#ff0000" in resp.data and b"#800000" in resp.data


def test_rejects_non_image(client):
    resp = client.post("/palette", data={"image": (io.BytesIO(b"hello"), "fake.png")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"not a valid image" in resp.data


def test_rejects_wrong_extension(client):
    resp = client.post("/", data={"image": (io.BytesIO(b"x"), "notes.txt")}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"Unsupported file type" in resp.data


def test_accepts_heic_and_returns_preview_on_request(client):
    buf = io.BytesIO()
    make_image().save(buf, format="HEIF")
    buf.seek(0)
    resp = client.post("/palette", data={"image": (buf, "IMG_0001.HEIC"), "need_preview": "1"},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.data.count(b'class="swatch"') == 2
    assert b'class="server-preview"' in resp.data


def test_no_server_preview_unless_asked(client):
    resp = client.post("/palette", data={"image": as_file(make_image())}, content_type="multipart/form-data")
    assert b"server-preview" not in resp.data
