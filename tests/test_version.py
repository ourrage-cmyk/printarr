from fastapi.testclient import TestClient

from app import version
from app.main import create_app


def test_healthz_reports_version_and_build_sha(settings, monkeypatch):
    monkeypatch.setenv("PRINTARR_BUILD_SHA", "abc1234def5678")
    with TestClient(create_app(settings)) as client:
        body = client.get("/healthz").json()
    assert body == {"status": "ok", "version": version.PACKAGE_VERSION, "git_sha": "abc1234def5678"}


def test_build_sha_is_dev_outside_ci(monkeypatch):
    monkeypatch.delenv("PRINTARR_BUILD_SHA", raising=False)
    assert version.build_info() == {"version": version.PACKAGE_VERSION, "git_sha": "dev"}
