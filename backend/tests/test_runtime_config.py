from __future__ import annotations

from pathlib import Path

import pytest

import missus_tom.config as config_module
import missus_tom.main as main_module
from missus_tom.config import settings


def test_resource_root_uses_explicit_environment_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resources = tmp_path / "resources"
    monkeypatch.setenv("MISSUS_TOM_RESOURCE_ROOT", str(resources))

    assert settings.resource_root == resources.resolve()


def test_resource_root_uses_pyinstaller_resource_directory_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MISSUS_TOM_RESOURCE_ROOT", raising=False)
    monkeypatch.setattr(config_module.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert settings.resource_root == tmp_path / "resources"


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", "127.0.0.1"), ("::1", "::1"), ("localhost", "localhost")],
)
def test_api_host_accepts_loopback_addresses(
    monkeypatch: pytest.MonkeyPatch, host: str, expected: str
) -> None:
    monkeypatch.setenv("MISSUS_TOM_API_HOST", host)

    assert settings.api_host == expected


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.test", ""])
def test_api_host_rejects_non_loopback_values(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("MISSUS_TOM_API_HOST", host)

    with pytest.raises(ValueError, match="loopback"):
        _ = settings.api_host


@pytest.mark.parametrize(("port", "expected"), [("1", 1), ("8000", 8000), ("65535", 65535)])
def test_api_port_accepts_valid_values(
    monkeypatch: pytest.MonkeyPatch, port: str, expected: int
) -> None:
    monkeypatch.setenv("MISSUS_TOM_API_PORT", port)

    assert settings.api_port == expected


@pytest.mark.parametrize("port", ["0", "65536", "-1", "not-a-port"])
def test_api_port_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("MISSUS_TOM_API_PORT", port)

    with pytest.raises(ValueError, match="MISSUS_TOM_API_PORT"):
        _ = settings.api_port


def test_run_starts_uvicorn_with_existing_app_and_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(application: object, **kwargs: object) -> None:
        captured["application"] = application
        captured.update(kwargs)

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    monkeypatch.setenv("MISSUS_TOM_API_HOST", "localhost")
    monkeypatch.setenv("MISSUS_TOM_API_PORT", "8765")

    main_module.run()

    assert captured == {
        "application": main_module.app,
        "host": "localhost",
        "port": 8765,
        "reload": False,
    }
