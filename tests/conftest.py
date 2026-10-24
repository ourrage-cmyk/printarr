import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "db" / "printarr.db"),
        output_dir=str(tmp_path / "out"),
        timezone="Europe/London",
        printer_mode="file",
        scheduler_enabled=False,
        setup_required=False,  # the wizard has its own tests in test_setup.py
    )
