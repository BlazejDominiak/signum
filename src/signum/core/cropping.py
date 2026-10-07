"""Wycinanie fragmentów stron z podpisami — do wizualnej weryfikacji przez człowieka.

Oprócz wycinka (zbliżenia) generujemy też miniaturę całej strony z narysowaną
ramką znaleziska: lokalizacja z modelu wizyjnego bywa przybliżona, a miniatura
pokazuje człowiekowi, GDZIE na stronie model coś zobaczył — nawet gdy sam
wycinek chybił.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

PAD_FRACTION = 0.15  # margines wokół ramki (ułamek jej wymiarów)
MIN_CROP_PX = 8  # ramki mniejsze niż to uznajemy za szum
MAX_AREA_FRACTION = 0.65  # ramka większa niż 65% strony to błąd modelu
BOX_SCALE = 1000  # model zwraca współrzędne w skali 0-1000
OVERVIEW_MAX_SIDE = 480  # px — dłuższy bok miniatury strony
OVERVIEW_JPEG_QUALITY = 75  # miniatury stron: JPEG jest kilkukrotnie mniejszy od PNG
_OVERVIEW_BOX_COLOR = "#c62828"


def crop_box_2d(page: Image.Image, box_2d: tuple[int, int, int, int]) -> Image.Image | None:
    """Wycina ramkę ``[ymin, xmin, ymax, xmax]`` (skala 0-1000) z obrazu strony.

    Zwraca ``None``, gdy ramka jest zdegenerowana lub nieprawdopodobna —
    lepiej nie pokazać wycinka niż pokazać błędny.
    """
    x0, y0, x1, y1 = _box_2d_pixels(page, box_2d)
    return _crop_pixels(page, x0, y0, x1, y1)


def overview_box_2d(
    page: Image.Image, box_2d: tuple[int, int, int, int]
) -> Image.Image | None:
    """Miniatura strony z zaznaczoną ramką ``box_2d`` (skala 0-1000)."""
    x0, y0, x1, y1 = _box_2d_pixels(page, box_2d)
    return _overview_pixels(page, x0, y0, x1, y1)


def crop_pdf_rect(
    page: Image.Image,
    rect_pt: tuple[float, float, float, float],
    page_size_pt: tuple[float, float],
    page_bbox_pt: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
) -> Image.Image | None:
    """Wycina prostokąt podany w punktach PDF (origin w lewym dolnym rogu)."""
    pixels = _pdf_rect_pixels(page, rect_pt, page_size_pt, page_bbox_pt, rotation)
    if pixels is None:
        return None
    return _crop_pixels(page, *pixels)


def overview_pdf_rect(
    page: Image.Image,
    rect_pt: tuple[float, float, float, float],
    page_size_pt: tuple[float, float],
    page_bbox_pt: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
) -> Image.Image | None:
    """Miniatura strony z zaznaczonym prostokątem podanym w punktach PDF."""
    pixels = _pdf_rect_pixels(page, rect_pt, page_size_pt, page_bbox_pt, rotation)
    if pixels is None:
        return None
    return _overview_pixels(page, *pixels)


def _box_2d_pixels(
    page: Image.Image, box_2d: tuple[int, int, int, int]
) -> tuple[float, float, float, float]:
    ymin, xmin, ymax, xmax = box_2d
    return (
        xmin / BOX_SCALE * page.width,
        ymin / BOX_SCALE * page.height,
        xmax / BOX_SCALE * page.width,
        ymax / BOX_SCALE * page.height,
    )


def _pdf_rect_pixels(
    page: Image.Image,
    rect_pt: tuple[float, float, float, float],
    page_size_pt: tuple[float, float],
    page_bbox_pt: tuple[float, float, float, float] | None = None,
    rotation: int = 0,
) -> tuple[float, float, float, float] | None:
    left, bottom, right, top = page_bbox_pt or (0, 0, *page_size_pt)
    page_w_pt, page_h_pt = right - left, top - bottom
    if page_w_pt <= 0 or page_h_pt <= 0:
        return None
    x0_pt, y0_pt, x1_pt, y1_pt = rect_pt
    points = []
    for x_pt, y_pt in ((x0_pt, y0_pt), (x0_pt, y1_pt), (x1_pt, y0_pt), (x1_pt, y1_pt)):
        x, y = (x_pt - left) / page_w_pt, (y_pt - bottom) / page_h_pt
        # /Rotate obraca stronę zgodnie z ruchem wskazówek zegara.
        x, y = {
            0: (x, 1 - y), 90: (y, x), 180: (1 - x, y), 270: (1 - y, 1 - x),
        }[rotation % 360]
        points.append((x * page.width, y * page.height))
    return (
        min(x for x, _ in points), min(y for _, y in points),
        max(x for x, _ in points), max(y for _, y in points),
    )


def _crop_pixels(
    page: Image.Image, x0: float, y0: float, x1: float, y1: float
) -> Image.Image | None:
    if x1 <= x0 or y1 <= y0:
        return None
    width = x1 - x0
    height = y1 - y0
    if width < MIN_CROP_PX or height < MIN_CROP_PX:
        return None
    if width * height > MAX_AREA_FRACTION * page.width * page.height:
        return None

    pad_x = width * PAD_FRACTION
    pad_y = height * PAD_FRACTION
    left = max(0, int(x0 - pad_x))
    top = max(0, int(y0 - pad_y))
    right = min(page.width, int(x1 + pad_x))
    bottom = min(page.height, int(y1 + pad_y))
    if right - left < MIN_CROP_PX or bottom - top < MIN_CROP_PX:
        return None
    return page.crop((left, top, right, bottom))


def _overview_pixels(
    page: Image.Image, x0: float, y0: float, x1: float, y1: float
) -> Image.Image | None:
    """Miniatura strony z czerwoną ramką wokół podanego obszaru.

    W odróżnieniu od wycinka ramka zbyt duża lub podejrzana NIE jest
    odrzucana — pokazanie, gdzie model wskazał (nawet błędnie), jest
    dla weryfikującego człowieka informacją, nie szumem.
    """
    if x1 <= x0 or y1 <= y0:
        return None
    thumb = page.copy()
    thumb.thumbnail((OVERVIEW_MAX_SIDE, OVERVIEW_MAX_SIDE), Image.Resampling.LANCZOS)
    scale_x = thumb.width / page.width
    scale_y = thumb.height / page.height
    line = max(2, round(max(thumb.size) / 160))
    left = max(0, round(x0 * scale_x) - line)
    top = max(0, round(y0 * scale_y) - line)
    right = min(thumb.width - 1, round(x1 * scale_x) + line)
    bottom = min(thumb.height - 1, round(y1 * scale_y) + line)
    if right <= left or bottom <= top:  # obszar całkowicie poza stroną
        return None
    ImageDraw.Draw(thumb).rectangle(
        (left, top, right, bottom), outline=_OVERVIEW_BOX_COLOR, width=line
    )
    return thumb


def to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def to_jpeg_bytes(image: Image.Image, quality: int = OVERVIEW_JPEG_QUALITY) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
