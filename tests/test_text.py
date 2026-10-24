from fastapi.testclient import TestClient

from app.escpos import GS, PRINT_BUFFER, encode
from app.receipt import Line, wrap
from app.text import GLYPH_BYTES, glyph_raster, printable, printed_as_question, transliterate
from app.main import create_app


def test_typography_becomes_ascii():
    assert transliterate("‘hi’ — “ok” …") == "'hi' - \"ok\" ..."


def test_accents_cp437_has_are_kept_and_others_lose_their_accent():
    assert transliterate("café ā ş") == "café a s"


def test_cyrillic_line_prints_as_glyph_image():
    assert printable("Привет") == ("Привет", True)


def test_emoji_prints_as_question_mark_and_is_reported():
    text, glyph = printable("hi \U0001F600")
    assert (text, glyph) == ("hi ?", False)
    assert printed_as_question("hi \U0001F600") == ["\U0001F600"]


def test_cjk_line_prints_question_marks_not_a_broken_image():
    text, glyph = printable("你好")
    assert glyph is False and text == "??"


def test_glyph_image_is_full_paper_width_and_fits_long_lines():
    width_bytes, height, data = glyph_raster("Привет " * 12)
    assert width_bytes == GLYPH_BYTES == 64
    assert len(data) == width_bytes * height
    assert height > 0


def test_cyrillic_name_encodes_as_raster_not_question_marks():
    payload = encode([Line("Привет")])
    assert GS + b"(L" in payload and PRINT_BUFFER in payload
    assert b"?\n" not in payload  # no text line with "?" in it


def test_plain_ascii_bytes_are_unchanged():
    assert encode([Line("Hello")]).count(b"Hello\n") == 1


def test_runs_of_spaces_are_kept_in_lines_and_bytes():
    assert wrap("a    b   c", 42) == ["a    b   c"]
    assert b"a    b\n" in encode([Line("a    b")])


def test_preview_warns_about_length_and_question_marks(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        long = client.post(
            "/api/v1/tickets/preview",
            json={"recipient": "yannic", "message": "\n".join(["line"] * 30)},
        ).json()
        assert any("lines long" in w for w in long["warnings"])

        emoji = client.post(
            "/api/v1/tickets/preview",
            json={"recipient": "wife", "message": "Hi \U0001F600"},
        ).json()
        assert any("\U0001F600" in w for w in emoji["warnings"])
        assert emoji["warnings"] and not any("lines long" in w for w in emoji["warnings"])


def test_glyph_lines_are_logged_with_their_source_text(settings, caplog):
    import logging

    from fastapi.testclient import TestClient

    from app.main import create_app

    caplog.set_level(logging.INFO, logger="printarr.scheduler")
    app = create_app(settings)
    with TestClient(app) as client:
        ticket = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "Привет, Алиса"}).json()
        assert app.state.scheduler.run_once() == 1
        assert ticket["id"]
    assert any("drawn as images" in r.message and "Привет, Алиса" in r.message for r in caplog.records)
