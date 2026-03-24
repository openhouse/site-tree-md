from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


_BOOTSTRAP_STATUS: RuntimeBootstrapStatus | None = None
_BOOTSTRAP_LOCK_WAIT_SECONDS = 0.1
_BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 300.0


class BrowserRuntimeBootstrapError(RuntimeError):
    """Raised when the browser runtime cannot be provisioned."""


@dataclass(slots=True)
class RuntimeBootstrapStatus:
    available: bool
    attempted: bool = False
    auto_installed: bool = False
    install_attempted: bool = False
    install_succeeded: bool = False
    warning: str | None = None
    package_installed: bool = False
    chromium_installed: bool = False
    playwright_version: str | None = None
    cache_marker_path: str | None = None

    def for_page(self) -> tuple[bool, bool, str | None]:
        return self.attempted, self.available, self.warning


def _cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "site-tree-md"


def _lock_path() -> Path:
    return _cache_dir() / "playwright-bootstrap.lock"


def _marker_path() -> Path:
    return _cache_dir() / "playwright-bootstrap.json"


def reset_runtime_bootstrap_state() -> None:
    global _BOOTSTRAP_STATUS
    _BOOTSTRAP_STATUS = None


def get_runtime_bootstrap_status() -> RuntimeBootstrapStatus | None:
    return _BOOTSTRAP_STATUS


def _wait_for_lock_release(path: Path) -> None:
    deadline = time.monotonic() + _BOOTSTRAP_LOCK_TIMEOUT_SECONDS
    while path.exists():
        if time.monotonic() >= deadline:
            raise BrowserRuntimeBootstrapError(
                f"Timed out waiting for browser runtime bootstrap lock: {path}"
            )
        time.sleep(_BOOTSTRAP_LOCK_WAIT_SECONDS)


def _acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _BOOTSTRAP_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise BrowserRuntimeBootstrapError(
                    f"Timed out waiting to acquire browser runtime bootstrap lock: {path}"
                )
            time.sleep(_BOOTSTRAP_LOCK_WAIT_SECONDS)


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _run(command: list[str], *, verbose: bool) -> subprocess.CompletedProcess[str]:
    kwargs = {"check": True, "text": True}
    if verbose:
        return subprocess.run(command, **kwargs)
    return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)


def _import_playwright() -> tuple[object, str | None]:
    module = importlib.import_module("playwright")
    sync_api = importlib.import_module("playwright.sync_api")
    version = getattr(module, "__version__", None)
    return sync_api, version


def _playwright_probe_code() -> str:
    return (
        "from playwright.sync_api import sync_playwright\n"
        "playwright = sync_playwright().start()\n"
        "browser = None\n"
        "try:\n"
        "    browser = playwright.chromium.launch(headless=True)\n"
        "finally:\n"
        "    if browser is not None:\n"
        "        browser.close()\n"
        "    playwright.stop()\n"
    )


def _probe_chromium_subprocess(*, verbose: bool) -> None:
    _run([sys.executable, "-c", _playwright_probe_code()], verbose=verbose)


def _looks_like_missing_browser(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(
        marker in lowered
        for marker in (
            "executable doesn't exist",
            "executable doesn't exist at",
            "please run the following command",
            "playwright install",
            "browser has been closed",
            "failed to launch browser",
        )
    )


def _load_marker() -> dict[str, str] | None:
    marker = _marker_path()
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_marker(version: str | None) -> None:
    marker = _marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "playwright_version": version,
                "browser": "chromium",
                "python": sys.version.split()[0],
                "bootstrapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def ensure_browser_runtime(*, verbose: bool = False) -> RuntimeBootstrapStatus:
    global _BOOTSTRAP_STATUS
    if _BOOTSTRAP_STATUS is not None:
        return _BOOTSTRAP_STATUS

    lock_path = _lock_path()
    _acquire_lock(lock_path)
    try:
        if _BOOTSTRAP_STATUS is not None:
            return _BOOTSTRAP_STATUS

        status = RuntimeBootstrapStatus(available=False, cache_marker_path=str(_marker_path()))
        sync_api = None
        version = None
        marker = _load_marker()

        try:
            sync_api, version = _import_playwright()
            status.package_installed = True
        except ImportError:
            status.attempted = True
            status.auto_installed = True
            status.install_attempted = True
            if verbose:
                print(
                    "Playwright missing; installing playwright and Chromium into current environment..."
                )
            try:
                _run(
                    [sys.executable, "-m", "pip", "install", "playwright>=1.52"],
                    verbose=verbose,
                )
                sync_api, version = _import_playwright()
                status.package_installed = True
            except Exception as exc:
                status.warning = f"playwright bootstrap failed: {exc}"
                _BOOTSTRAP_STATUS = status
                raise BrowserRuntimeBootstrapError(status.warning) from exc

        status.playwright_version = version

        try:
            _probe_chromium_subprocess(verbose=verbose)
            status.available = True
            status.chromium_installed = True
            status.install_succeeded = status.install_attempted
            if status.install_attempted:
                _write_marker(version)
            _BOOTSTRAP_STATUS = status
            return status
        except Exception as exc:
            status.attempted = True
            error_text = str(exc)
            if not _looks_like_missing_browser(error_text):
                status.warning = f"playwright bootstrap failed: {exc}"
                _BOOTSTRAP_STATUS = status
                if verbose:
                    print(f"Browser runtime bootstrap failed: {status.warning}")
                raise BrowserRuntimeBootstrapError(status.warning) from exc
            status.auto_installed = True
            status.install_attempted = True
            if verbose:
                print("Chromium missing or not launchable; installing Chromium for Playwright...")
            try:
                _run([sys.executable, "-m", "playwright", "install", "chromium"], verbose=verbose)
                _probe_chromium_subprocess(verbose=verbose)
                status.available = True
                status.chromium_installed = True
                status.install_succeeded = True
                _write_marker(version)
                if verbose:
                    print("Browser runtime bootstrap succeeded.")
                _BOOTSTRAP_STATUS = status
                return status
            except Exception as install_exc:
                status.warning = f"playwright bootstrap failed: {install_exc}"
                _BOOTSTRAP_STATUS = status
                if verbose:
                    print(f"Browser runtime bootstrap failed: {status.warning}")
                raise BrowserRuntimeBootstrapError(status.warning) from install_exc
    finally:
        _release_lock(lock_path)
        _wait_for_lock_release(lock_path)
