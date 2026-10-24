"""Ticket images: a PNG of each ticket as it reached the printer, newest kept, recalled by ticket id."""

import io
import os
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ticket_images
from app.escpos import encode
from app.escpos_image import payload_to_png
from app.main import create_app
from app.receipt import Line
from app.scheduler import Scheduler
from app.store import TicketStore
from tests.test_store_scheduler import RecordingTransport, create

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def store(settings):
    s = TicketStore(settings.db_path)
    s.init()
    return s


def _png(text="hello"):
    return payload_to_png(encode([Line(text)], feed=1, raster_mode="gs_l"))


def test_png_is_paper_width_and_valid(settings):
    png = _png()
    assert png.startswith(PNG_SIGNATURE)
    assert Image.open(io.BytesIO(png)).size[0] == 512  # 80 mm paper, 1 dot per pixel


def test_only_ticket_ids_map_to_files(settings):
    images = settings.images_dir
    ticket_id = uuid.uuid4().hex
    assert ticket_images.image_path(images, ticket_id) == images / f"{ticket_id}.png"
    for bad in ["../../etc/passwd", "ABCDEF", "a" * 31, "a" * 33, "g" * 32, "%2e%2e"]:
        assert ticket_images.image_path(images, bad) is None


def test_prune_keeps_the_newest(tmp_path):
    ids = [uuid.uuid4().hex for _ in range(5)]
    for offset, ticket_id in enumerate(ids):
        path = tmp_path / f"{ticket_id}.png"
        path.write_bytes(b"x")
        os.utime(path, (1_000 + offset, 1_000 + offset))  # ids[4] is the newest
    removed = ticket_images.prune(tmp_path, keep=3)
    assert set(removed) == set(ids[:2])
    assert ticket_images.recent(tmp_path, 10) == [ids[4], ids[3], ids[2]]


def test_save_writes_and_prunes_older_images(tmp_path):
    ids = [uuid.uuid4().hex for _ in range(4)]
    for ticket_id in ids:
        ticket_images.save(tmp_path, ticket_id, _png(), keep=3)
    assert len(list(tmp_path.glob("*.png"))) == 3
    assert not list(tmp_path.glob("*.tmp"))  # the write is atomic: no partial files left behind
    assert ticket_images.recent(tmp_path, 10)[0] == ids[3]


def test_printed_ticket_keeps_its_image(store, settings):
    ticket = create(store)
    assert Scheduler(store, RecordingTransport(), settings, clock=lambda: 5_000).run_once() == 1
    path = ticket_images.image_path(settings.images_dir, ticket["id"])
    assert path.read_bytes().startswith(PNG_SIGNATURE)


def test_failed_ticket_keeps_image_and_logs_its_path(store, settings, caplog):
    ticket = create(store)
    scheduler = Scheduler(store, RecordingTransport(fail=1), settings, clock=lambda: 5_000)
    scheduler.run_once()
    path = ticket_images.image_path(settings.images_dir, ticket["id"])
    assert path.is_file()
    assert store.get(ticket["id"])["status"] != "sent"
    assert f"(image: {path})" in caplog.text


def test_images_are_capped_by_setting(store, settings):
    capped = replace(settings, image_keep=2)
    for _ in range(3):
        create(store)
    Scheduler(store, RecordingTransport(), capped, clock=lambda: 5_000).run_once()
    assert len(list(capped.images_dir.glob("*.png"))) == 2


def test_api_lists_and_recalls_images(settings):
    png = _png("recall me")
    with TestClient(create_app(settings)) as client:
        ticket_id = client.post("/api/v1/tickets", json={"recipient": "wife", "message": "Hi"}).json()["id"]
        assert client.get(f"/api/v1/tickets/{ticket_id}/image").status_code == 404  # not printed yet
        ticket_images.save(settings.images_dir, ticket_id, png, keep=250)

        listed = client.get("/api/v1/ticket-images").json()
        assert [row["id"] for row in listed] == [ticket_id]
        row = listed[0]
        assert row["recipient"] == "wife" and row["status"] and row["kind"] and row["template_id"] is not None
        assert row["image_url"] == f"/api/v1/tickets/{ticket_id}/image"

        recalled = client.get(row["image_url"])
        assert recalled.status_code == 200
        assert recalled.headers["content-type"] == "image/png"
        assert recalled.content == png


def test_api_says_why_there_is_no_image(settings):
    with TestClient(create_app(settings)) as client:
        missing = client.get(f"/api/v1/tickets/{uuid.uuid4().hex}/image")
        assert missing.status_code == 404
        assert client.get("/api/v1/tickets/..%2F..%2Fsecret/image").status_code == 404
        assert client.get("/api/v1/ticket-images?limit=0").status_code == 422


def held_for_release(store):
    return store.create(
        recipient="yannic", message="held", send_at_ms=0, template_id=1, decorations=(),
        selection="rule", held=True, delivery="on_release",
    )


def test_released_strip_keeps_an_image_per_ticket(store, settings):
    first, second = held_for_release(store), held_for_release(store)
    scheduler = Scheduler(store, RecordingTransport(), settings, clock=lambda: 5_000)
    strips = scheduler.print_release("yannic", "morning")
    assert len(strips) == 1
    for ticket in (first, second):
        assert ticket_images.image_path(settings.images_dir, ticket["id"]).is_file()


def test_failed_strip_keeps_each_ticket_image(store, settings):
    from app.scheduler import ReleaseIncomplete

    first, second = held_for_release(store), held_for_release(store)
    scheduler = Scheduler(store, RecordingTransport(fail=1), settings, clock=lambda: 5_000)
    with pytest.raises(ReleaseIncomplete):
        scheduler.print_release("yannic", "morning")
    for ticket in (first, second):
        assert ticket_images.image_path(settings.images_dir, ticket["id"]).is_file()
        assert store.get(ticket["id"])["status"] == "held"  # back on hold for the next release
