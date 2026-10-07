"""Renderowanie dokumentów do obrazów rastrowych.

PDF-y renderuje pypdfium2 (licencja BSD/Apache), pliki graficzne wczytuje
Pillow. Obrazy stron trzymamy w pełnej rozdzielczości roboczej (do wycinków
podpisów), a do modelu AI wysyłamy pomniejszoną kopię JPEG.
"""

from __future__ import annotations

import io
import math
import warnings
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from signum.core.discovery import PDF_EXTENSIONS

RENDER_SCALE = 150 / 72  # rendering PDF w ~150 DPI
MAX_WORKING_SIDE = 2400  # px — limit pamięci dla obrazu roboczego
JPEG_QUALITY = 85
MAX_INPUT_FILE_BYTES = 250 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000

# Ostrzeżenie Pillow zamieniamy niżej w błąd, zanim obraz zostanie w pełni
# zdekompresowany. Limit 50 Mpx nadal obejmuje duże skany biurowe.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class DocumentReadError(Exception):
    """Nie udało się odczytać/wyrenderować dokumentu."""


@dataclass(slots=True)
class PageImage:
    """Jedna strona dokumentu wyrenderowana do obrazu.

    ``page_size_pt`` jest ustawione tylko dla PDF (potrzebne do mapowania
    prostokątów pól podpisu z układu współrzędnych PDF na piksele).
    """

    number: int  # 1-bazowy numer strony
    image: Image.Image  # RGB, pełna rozdzielczość robocza
    page_size_pt: tuple[float, float] | None = None  # (szerokość, wysokość) w punktach
    page_bbox_pt: tuple[float, float, float, float] | None = None
    rotation: int = 0


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() in PDF_EXTENSIONS


def load_pages(path: Path, max_pages: int) -> tuple[list[PageImage], int]:
    """Wczytuje kopie stron do listy. Analiza używa strumieniowego ``open_pages``."""
    with open_pages(path, max_pages) as (pages, total):
        return [
            PageImage(p.number, p.image.copy(), p.page_size_pt, p.page_bbox_pt, p.rotation)
            for p in pages
        ], total


@contextmanager
def open_pages(path: Path, max_pages: int) -> Iterator[tuple[Iterator[PageImage], int]]:
    """Udostępnia strony pojedynczo; obraz jest ważny do kolejnego kroku iteratora.

    Zamknięcie kontekstu zwalnia bieżący obraz i dokument również po błędzie
    modelu lub anulowaniu. Wyjątki konsumenta nie są błędami odczytu pliku.
    """
    with ExitStack() as resources:
        try:
            size = path.stat().st_size
            if size > MAX_INPUT_FILE_BYTES:
                raise DocumentReadError(
                    f"Plik ma {size / (1024 * 1024):.1f} MB; limit bezpieczeństwa wynosi "
                    f"{MAX_INPUT_FILE_BYTES // (1024 * 1024)} MB"
                )
            limit = max(1, min(int(max_pages), 500))
            if is_pdf(path):
                pdf = pdfium.PdfDocument(str(path))
                resources.callback(pdf.close)
                total = len(pdf)
                pages = _iter_pdf_pages(pdf, min(total, limit))
            else:
                resources.enter_context(warnings.catch_warnings())
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                source = resources.enter_context(Image.open(path))
                total = getattr(source, "n_frames", 1)
                pages = _iter_image_pages(source, min(total, limit))
        except Exception as exc:
            raise DocumentReadError(f"Nie można odczytać pliku: {exc}") from exc
        resources.callback(pages.close)
        yield pages, total


def render_pdf_page(path: Path, page_number: int) -> PageImage:
    """Renderuje pojedynczą stronę PDF (1-bazowa) — np. dla wycinka podpisu
    cyfrowego leżącego poza zakresem stron analizowanych wizyjnie."""
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise DocumentReadError(f"Nie można otworzyć PDF: {exc}") from exc
    try:
        if not 1 <= page_number <= len(pdf):
            raise DocumentReadError(f"Strona {page_number} poza zakresem")
        return _render_page(pdf, page_number)
    except Exception as exc:
        raise DocumentReadError(f"Nie można odczytać strony {page_number}: {exc}") from exc
    finally:
        pdf.close()


def _iter_pdf_pages(pdf: pdfium.PdfDocument, count: int) -> Generator[PageImage, None, None]:
    for number in range(1, count + 1):
        try:
            page = _render_page(pdf, number)
        except Exception as exc:
            raise DocumentReadError(f"Nie można odczytać strony {number}: {exc}") from exc
        try:
            yield page
        finally:
            page.image.close()


def _render_page(pdf: pdfium.PdfDocument, page_number: int) -> PageImage:
    page = pdf[page_number - 1]
    try:
        return _render_open_page(page, page_number)
    finally:
        page.close()


def _render_open_page(page: pdfium.PdfPage, page_number: int) -> PageImage:
    width_pt, height_pt = page.get_size()
    if (
        not math.isfinite(width_pt)
        or not math.isfinite(height_pt)
        or width_pt <= 0
        or height_pt <= 0
    ):
        raise DocumentReadError("PDF zawiera niepoprawny rozmiar strony")
    scale = RENDER_SCALE
    longest = max(width_pt, height_pt) * scale
    if longest > MAX_WORKING_SIDE:
        scale = MAX_WORKING_SIDE / max(width_pt, height_pt)
    bitmap = page.render(scale=scale)
    try:
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    return PageImage(
        number=page_number, image=image, page_size_pt=(width_pt, height_pt),
        page_bbox_pt=page.get_bbox(), rotation=page.get_rotation(),
    )


def _iter_image_pages(source: Image.Image, count: int) -> Generator[PageImage, None, None]:
    for frame in range(count):
        try:
            source.seek(frame)
            with ImageOps.exif_transpose(source) as oriented:
                rgb = oriented.convert("RGB")
            image = _cap_size(rgb)
            if image is not rgb:
                rgb.close()
        except Exception as exc:
            raise DocumentReadError(f"Nie można odczytać obrazu {frame + 1}: {exc}") from exc
        try:
            yield PageImage(number=frame + 1, image=image)
        finally:
            image.close()


def _cap_size(image: Image.Image) -> Image.Image:
    longest = max(image.size)
    if longest <= MAX_WORKING_SIDE:
        return image
    ratio = MAX_WORKING_SIDE / longest
    new_size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def to_model_jpeg(image: Image.Image, max_side: int) -> bytes:
    """Pomniejszona kopia strony jako JPEG — wejście dla modelu wizyjnego."""
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    copy.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
