"""A PDF's first page, rendered in the backend by the bundled renderer, in a child process, as a PNG with no Pillow.

The PDF is built here, by hand — no file from anywhere else is read and nothing is fetched."""
from __future__ import annotations

import struct
import zlib

import pytest

from api.services import entity_picture, media_preview, pdf_page

pytest.importorskip("pypdfium2")


def minimal_pdf(width=300, height=400) -> bytes:
    """One page: a line of text and a solid blue rectangle at a known place."""
    stream = b"BT /F1 24 Tf 40 300 Td (alpha-project) Tj ET 0 0 1 rg 40 40 200 100 re f"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>" % (width, height),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def pixel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    width, height = struct.unpack(">II", png[16:24])
    raw = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
    row = 1 + width * 3
    assert raw[y * row] == 0, "filter type None, as encode_png writes it"
    i = y * row + 1 + x * 3
    return tuple(raw[i:i + 3])


def test_page_one_is_rendered_to_a_png_the_picture_store_keeps():
    png = pdf_page.render_first_page(minimal_pdf())
    assert png is not None
    assert entity_picture.validate_upload(png) == "png"
    assert media_preview.accept_image(png) == "png"
    assert entity_picture.dimensions(png) == (480, 640)
    # The blue rectangle sits at (40..240, 40..140) in PDF units from the bottom-left; scale 1.6.
    assert pixel(png, 200, 640 - 150) == (0, 0, 255)
    assert pixel(png, 5, 5) == (255, 255, 255)


def test_a_tall_page_is_capped_at_the_stores_largest_side():
    png = pdf_page.render_first_page(minimal_pdf(300, 3000))
    width, height = entity_picture.dimensions(png)
    assert height <= pdf_page.MAX_SIDE and width < pdf_page.WIDTH


@pytest.mark.parametrize("data", [b"", b"not a pdf", b"%PDF-1.4\n garbage that is no document",
                                  minimal_pdf()[:200]])
def test_what_cannot_be_drawn_is_none_never_a_crash(data):
    assert pdf_page.render_first_page(data) is None


def test_a_hung_renderer_is_cut_off(monkeypatch):
    assert pdf_page.render_first_page(minimal_pdf(), timeout_s=0.001) is None


def test_the_png_encoder_round_trips():
    png = pdf_page.encode_png(2, 1, b"\x01\x02\x03\x04\x05\x06\xff", 7)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and entity_picture.dimensions(png) == (2, 1)
    assert pixel(png, 1, 0) == (4, 5, 6)


def test_scale_for_fits_the_width_or_the_height():
    assert pdf_page.scale_for(300, 400) == pytest.approx(1.6)
    assert pdf_page.scale_for(100, 10000) == pytest.approx(pdf_page.MAX_SIDE / 10000)
    assert pdf_page.scale_for(0, 10) == 0.0
