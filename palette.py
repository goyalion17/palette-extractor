import colorsys
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from PIL import Image, ImageOps

# більше пікселів майже не змінює результат, а рахується довше
ANALYSIS_SIZE = (300, 300)
# злиття — квадратичне, тож зливаємо лише найчастіші кольори; рідкісний «хвіст» у топ не потрапить
MERGE_LIMIT = 1024


@dataclass
class Color:
    rgb: tuple
    share: float

    @property
    def hex(self):
        return "#{:02x}{:02x}{:02x}".format(*self.rgb)

    @property
    def hsl(self):
        h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in self.rgb))
        return f"hsl({round(h * 360)}, {round(s * 100)}%, {round(l * 100)}%)"

    @property
    def luminance(self):
        # відносна яскравість за WCAG 2.x
        def channel(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(v) for v in self.rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @property
    def is_light(self):
        # світлий, якщо чорний текст на ньому контрастніший за білий
        return self.luminance > 0.179


def contrast_ratio(a, b):
    hi, lo = sorted((a.luminance, b.luminance), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def accessible_pairs(colors, min_ratio=4.5, limit=6):
    """Пари кольорів палітри, які годяться для тексту на фоні (WCAG AA — від 4.5:1)."""
    pairs = [(a, b, contrast_ratio(a, b)) for a, b in combinations(colors, 2)]
    pairs = [p for p in pairs if p[2] >= min_ratio]
    return sorted(pairs, key=lambda p: p[2], reverse=True)[:limit]


def _merge_similar(features, tol):
    """Жадібно зливає схожі кольори в найчастіший серед них.

    features відсортовані за спаданням частоти. Повертає (keep, assign):
    індекси кольорів-«представників» і номер групи для кожного кольору.
    """
    reps = np.empty_like(features)
    keep = []
    assign = np.empty(len(features), dtype=int)
    for i, f in enumerate(features):
        k = len(keep)
        if k:
            close = np.flatnonzero(np.abs(reps[:k] - f).max(axis=1) <= tol)
            if close.size:
                assign[i] = close[0]
                continue
        reps[k] = f
        keep.append(i)
        assign[i] = k
    return np.array(keep, dtype=int), assign


def extract_palette(image, n_colors=10, delta=24, reduce_gradient=True, reduce_brightness=True):
    """Повертає (colors, labels): n_colors найчастіших кольорів і карту пікселів.

    delta — крок квантування: близькі відтінки зливаються в один колір,
    інакше на фото майже кожен піксель був би «окремим» кольором.
    reduce_gradient — зливає сусідні «кошики» (плавні переходи кольору).
    reduce_brightness — зливає світлі й темні варіанти одного кольору.
    labels — масив розміру зменшеної картинки: номер кольору в палітрі або -1.
    """
    img = ImageOps.exif_transpose(image).convert("RGBA")
    img.thumbnail(ANALYSIS_SIZE)

    pixels = np.asarray(img).reshape(-1, 4)
    # прозорі пікселі (png) не рахуємо
    opaque = pixels[:, 3] > 127
    rgb = pixels[opaque][:, :3].astype(np.int64)
    labels = np.full(len(pixels), -1)
    if rgb.size == 0:
        return [], labels.reshape(img.height, img.width)

    quantized = (rgb // delta) * delta + delta // 2
    # пакуємо r, g, b в одне число — так np.unique працює по 1D-масиву і швидко
    packed = (quantized[:, 0] << 16) | (quantized[:, 1] << 8) | quantized[:, 2]
    values, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)
    # справжній середній колір кожного кошика — він і піде в HEX, а не центр кошика
    sums = np.zeros((len(values), 3))
    np.add.at(sums, inverse, rgb)
    means = sums / counts[:, None]

    order = np.argsort(counts, kind="stable")[::-1]
    centers = np.stack([values >> 16, (values >> 8) & 0xFF, values & 0xFF], axis=1)[order]
    counts, means = counts[order], means[order]
    # group[кошик] — номер групи; спершу кожен кошик сам собі група
    group = np.empty(len(values), dtype=int)
    group[order] = np.arange(len(values))
    # частки рахуємо від усіх пікселів, навіть якщо хвіст відкинемо
    total = counts.sum()

    def regroup(keep, assign):
        nonlocal group, centers, counts, means
        group = np.where(group >= 0, assign[group], -1)
        merged = np.zeros(len(keep), dtype=counts.dtype)
        np.add.at(merged, assign, counts)
        # колір групи — колір її найчастішого кошика, а не «каламутне» середнє всіх
        centers, counts, means = centers[keep], merged, means[keep]

    if reduce_gradient or reduce_brightness:
        group[group >= MERGE_LIMIT] = -1
        centers, counts, means = centers[:MERGE_LIMIT], counts[:MERGE_LIMIT], means[:MERGE_LIMIT]
    if reduce_gradient:
        # сусідні кошики відрізняються рівно на delta в кожному каналі
        regroup(*_merge_similar(centers, delta))
    if reduce_brightness:
        # у сірих, чорного й білого немає відтінку — це не «версії» одного кольору, тож їх не зливаємо
        gray = np.ptp(centers, axis=1) <= delta
        chroma_idx, gray_idx = np.flatnonzero(~gray), np.flatnonzero(gray)
        # масштабуємо колір так, щоб найяскравіший канал став 255:
        # темно-червоний і червоний тоді стають майже однаковими
        chroma = centers[chroma_idx]
        scaled = chroma * 255 // np.maximum(chroma.max(axis=1, keepdims=True), 1)
        keep, assign_chroma = _merge_similar(scaled, delta)
        assign = np.empty(len(centers), dtype=int)
        assign[chroma_idx] = assign_chroma
        assign[gray_idx] = len(keep) + np.arange(len(gray_idx))
        regroup(np.concatenate([chroma_idx[keep], gray_idx]), assign)

    top = np.argsort(counts, kind="stable")[::-1][:n_colors]
    colors = [Color(tuple(int(v) for v in np.rint(means[i])), counts[i] / total) for i in top]

    # номер у палітрі для кожної групи; групи поза топом і відкинутий хвіст — -1
    rank = np.full(len(counts), -1)
    rank[top] = np.arange(len(top))
    pixel_group = group[inverse]
    labels[opaque] = np.where(pixel_group >= 0, rank[pixel_group], -1)
    return colors, labels.reshape(img.height, img.width)
