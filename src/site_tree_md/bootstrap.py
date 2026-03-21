from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_BOOTSTRAP_STATUS: BrowserRuntimeStatus | None = None
_CACHE_VERSION = 1


@dataclass(slots=True)
class BrowserRuntimeStatus:
    required: bool
    available: bool
    auto_installed: bool
    install_attempted: bool
    install_succeeded: bool
    warning: str | None = None
    package_installed: bool = False
    browser_installed: bool = False
    package_version: str | None = None
    cache_marker_path: str | None = None


class BrowserRuntimeBootstrapError(RuntimeError):
    pass


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> _FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+", encoding="utf-8")
        if os.name == "nt":  # pragma: no cover
            import msvcrt

            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._fh is None:
            return
        if os.name == "nt":  # pragma: no cover
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()
        self._fh = None


def _cache_dir() -> Path:
    return Path.home() / ".cache" / "site-tree-md"


def _marker_path() -> Path:
    return _cache_dir() / "browser-runtime.json"


def _lock_path() -> Path:
    return _cache_dir() / "browser-runtime.lock"


def _import_playwright_sync_api():
    return importlib.import_module("playwright.sync_api")


def _playwright_version() -> str | None:
    try:
        module = importlib.import_module("playwright")
    except ImportError:
        return None
    return getattr(module, "__version__", None)


def _load_marker() -> dict[str, object] | None:
    marker_path = _marker_path()
    if not marker_path.exists():
        return None
    try:
        return json.loads(marker_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_marker(browser_name: str) -> None:
    marker_path = _marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "cache_version": _CACHE_VERSION,
                "browser_name": browser_name,
                "package_version": _playwright_version(),
                "python_version": sys.version.split()[0],
                "timestamp": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _run_command(cmd: list[str], verbose: bool = False) -> None:
    stdout = None if verbose else subprocess.DEVNULL
    stderr = None if verbose else subprocess.DEVNULL
    subprocess.run(cmd, check=True, stdout=stdout, stderr=stderr)


def _probe_browser(verbose: bool = False) -> tuple[bool, str | None]:
    try:
        sync_api = _import_playwright_sync_api()
        with sync_api.sync_playwright().start() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True, None
    except Exception as exc:  # pragma: no cover - exercised via tests/mocks
        if verbose:
            print(f"Browser runtime probe failed: {exc}")
        return False, str(exc)


def ensure_browser_runtime(
    verbose: bool = False, browser_name: str = "chromium"
) -> BrowserRuntimeStatus:
    global _BOOTSTRAP_STATUS
    if _BOOTSTRAP_STATUS is not None:
        return _BOOTSTRAP_STATUS

    status = BrowserRuntimeStatus(
        required=True,
        available=False,
        auto_installed=False,
        install_attempted=False,
        install_succeeded=False,
        cache_marker_path=str(_marker_path()),
    )

    with _FileLock(_lock_path()):
        if _BOOTSTRAP_STATUS is not None:
            return _BOOTSTRAP_STATUS

        marker = _load_marker()
        playwright_version = _playwright_version()
        if (
            marker
            and marker.get("cache_version") == _CACHE_VERSION
            and marker.get("browser_name") == browser_name
            and marker.get("package_version") == playwright_version
        ):
            ok, warning = _probe_browser(verbose=verbose)
            if ok:
                status.available = True
                status.install_succeeded = True
                status.package_installed = playwright_version is not None
                status.browser_installed = True
                status.package_version = playwright_version
                _BOOTSTRAP_STATUS = status
                return status
            status.warning = warning

        try:
            _import_playwright_sync_api()
            status.package_installed = True
        except ImportError:
            status.install_attempted = True
            status.auto_installed = True
            if verbose:
                print(
                    "Playwright missing; installing playwright and Chromium into current "
                    "environment…"
                )
            try:
                _run_command([sys.executable, "-m", "pip", "install", "playwright>=1.52"], verbose)
            except subprocess.CalledProcessError as exc:
                status.warning = f"failed to install playwright package: {exc}"
                _BOOTSTRAP_STATUS = status
                return status
            importlib.invalidate_caches()
            try:
                _import_playwright_sync_api()
                status.package_installed = True
            except ImportError as exc:
                status.warning = f"playwright remains unavailable after install: {exc}"
                _BOOTSTRAP_STATUS = status
                return status

        ok, warning = _probe_browser(verbose=verbose)
        if ok:
            status.available = True
            status.install_succeeded = True
            status.browser_installed = True
            status.package_version = _playwright_version()
            _write_marker(browser_name)
            if verbose and status.auto_installed:
                print("Browser runtime bootstrap succeeded.")
            _BOOTSTRAP_STATUS = status
            return status

        status.install_attempted = True
        if verbose and not status.auto_installed:
            print("Chromium missing or unusable; installing Chromium into current environment…")
        elif verbose:
            print("Browser runtime probe failed; installing Chromium into current environment…")
        try:
            _run_command([sys.executable, "-m", "playwright", "install", browser_name], verbose)
        except subprocess.CalledProcessError as exc:
            status.warning = f"failed to install {browser_name}: {exc}"
            _BOOTSTRAP_STATUS = status
            return status
        status.auto_installed = True
        ok, warning = _probe_browser(verbose=verbose)
        status.install_succeeded = ok
        status.available = ok
        status.browser_installed = ok
        status.package_version = _playwright_version()
        status.warning = None if ok else warning
        if ok:
            _write_marker(browser_name)
            if verbose:
                print("Browser runtime bootstrap succeeded.")
        _BOOTSTRAP_STATUS = status
        return status


def require_browser_runtime(verbose: bool = False) -> BrowserRuntimeStatus:
    status = ensure_browser_runtime(verbose=verbose)
    if not status.available:
        raise BrowserRuntimeBootstrapError(status.warning or "browser runtime is unavailable")
    return status


def reset_browser_runtime_state() -> None:
    global _BOOTSTRAP_STATUS
    _BOOTSTRAP_STATUS = None
