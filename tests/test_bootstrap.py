from __future__ import annotations

import importlib
import types

import pytest

from site_tree_md import bootstrap
from site_tree_md.bootstrap import BrowserRuntimeBootstrapError, ensure_browser_runtime


@pytest.fixture(autouse=True)
def reset_bootstrap_state() -> None:
    bootstrap.reset_runtime_bootstrap_state()


class DummyBrowser:
    def close(self) -> None:
        return


class DummyPlaywrightRuntime:
    def __init__(self) -> None:
        self.chromium = types.SimpleNamespace(launch=lambda headless=True: DummyBrowser())

    def stop(self) -> None:
        return


class DummySyncApi:
    @staticmethod
    def sync_playwright():
        return types.SimpleNamespace(start=lambda: DummyPlaywrightRuntime())


def test_missing_playwright_triggers_auto_install_once(monkeypatch) -> None:
    calls: list[list[str]] = []
    imported = {"installed": False}

    real_import_module = importlib.import_module

    def fake_import_module(name: str):
        if name == "playwright":
            if not imported["installed"]:
                raise ImportError("missing playwright")
            return types.SimpleNamespace(__version__="1.52.0")
        if name == "playwright.sync_api":
            if not imported["installed"]:
                raise ImportError("missing playwright")
            return DummySyncApi
        return real_import_module(name)

    def fake_run(command, **kwargs):  # noqa: ANN001
        calls.append(command)
        imported["installed"] = True
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    status = ensure_browser_runtime(verbose=False)
    status_second = ensure_browser_runtime(verbose=False)

    assert status.available is True
    assert status.install_attempted is True
    assert status.install_succeeded is True
    assert calls[0][:4] == [bootstrap.sys.executable, "-m", "pip", "install"]
    assert calls[1] == [bootstrap.sys.executable, "-m", "playwright", "install", "chromium"]
    assert status_second is status
    assert len(calls) == 2


def test_missing_chromium_triggers_browser_install_once(monkeypatch) -> None:
    calls: list[list[str]] = []
    probe_calls = {"count": 0}

    monkeypatch.setattr(bootstrap, "_import_playwright", lambda: (DummySyncApi, "1.52.0"))

    def fake_probe(sync_api_module):  # noqa: ANN001
        probe_calls["count"] += 1
        if probe_calls["count"] == 1:
            raise RuntimeError("Executable doesn't exist")

    def fake_run(command, **kwargs):  # noqa: ANN001
        calls.append(command)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap, "_probe_chromium", fake_probe)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    status = ensure_browser_runtime(verbose=False)

    assert status.available is True
    assert status.install_attempted is True
    assert status.install_succeeded is True
    assert calls == [[bootstrap.sys.executable, "-m", "playwright", "install", "chromium"]]
    assert probe_calls["count"] == 2


def test_bootstrap_failure_raises_clean_error(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_import_playwright", lambda: (_ for _ in ()).throw(ImportError("nope")))

    def fake_run(command, **kwargs):  # noqa: ANN001
        raise RuntimeError("pip failed")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    with pytest.raises(BrowserRuntimeBootstrapError, match="playwright bootstrap failed"):
        ensure_browser_runtime(verbose=False)
