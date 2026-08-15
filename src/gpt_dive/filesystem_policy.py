from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

from pydantic_monty import AbstractOS, MontyFileHandle, StatResult
from pydantic_monty.os_access import path_from_arg

GLOBAL_SECRET_PATTERNS = (
    "**/.env",
    "**/.env.*",
    "**/*.key",
    "**/*.pem",
    "**/secrets*",
)

HOME_SECRET_PATTERNS = (
    ".credentials",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".ssh",
    ".ssh/**",
    ".gnupg",
    ".gnupg/**",
    ".local/share/keyrings",
    ".local/share/keyrings/**",
    ".aws/credentials",
    ".docker/config.json",
    ".kube/config",
    ".config/gcloud/credentials.db",
    ".config/gcloud/application_default_credentials.json",
)


def _matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(path, pattern[3:])
    return False


def is_secret_path(path: Path, *, home: Path) -> bool:
    canonical = path.resolve()
    absolute_text = canonical.as_posix().lstrip("/")
    if any(_matches(absolute_text, pattern) for pattern in GLOBAL_SECRET_PATTERNS):
        return True
    try:
        home_relative = canonical.relative_to(home).as_posix()
    except ValueError:
        return False
    return any(_matches(home_relative, pattern) for pattern in HOME_SECRET_PATTERNS)


def harness_denied_patterns(*, root: Path, home: Path) -> tuple[str, ...]:
    root = root.resolve()
    home = home.resolve()
    if root == Path("/"):
        home_from_root = home.relative_to(Path("/")).as_posix()
        return (
            *GLOBAL_SECRET_PATTERNS,
            *(f"{home_from_root}/{pattern}" for pattern in HOME_SECRET_PATTERNS),
        )
    if root == home:
        return (*GLOBAL_SECRET_PATTERNS, *HOME_SECRET_PATTERNS)
    raise ValueError(f"unsupported Code Mode filesystem root: {root}")


class HostFileSystemOS(AbstractOS):
    """Host-backed Monty filesystem with broad reads and home-scoped writes."""

    def __init__(self, *, cwd: str | Path, home: str | Path) -> None:
        self.cwd = Path(cwd).expanduser().resolve()
        self.home = Path(home).expanduser().resolve()

    def _lexical(self, arg: PurePosixPath | MontyFileHandle) -> Path:
        raw = Path(str(path_from_arg(arg)))
        if raw.is_absolute():
            return raw
        return self.cwd / raw

    def _path(self, arg: PurePosixPath | MontyFileHandle, *, write: bool = False) -> Path:
        canonical = self._lexical(arg).resolve()
        if is_secret_path(canonical, home=self.home):
            raise PermissionError(f"Credential/secret path is blocked: {canonical}")
        if write and not canonical.is_relative_to(self.home):
            raise PermissionError(f"Write path is outside the Code Mode home root: {canonical}")
        return canonical

    def path_exists(self, path: PurePosixPath) -> bool:
        return self._path(path).exists()

    def path_is_file(self, path: PurePosixPath) -> bool:
        return self._path(path).is_file()

    def path_is_dir(self, path: PurePosixPath) -> bool:
        return self._path(path).is_dir()

    def path_is_symlink(self, path: PurePosixPath) -> bool:
        lexical = self._lexical(path)
        self._path(path)
        return lexical.is_symlink()

    def path_read_text(self, path: PurePosixPath | MontyFileHandle) -> str:
        return self._path(path).read_text()

    def path_read_bytes(self, path: PurePosixPath | MontyFileHandle) -> bytes:
        return self._path(path).read_bytes()

    def path_write_text(self, path: PurePosixPath | MontyFileHandle, data: str) -> int:
        return self._path(path, write=True).write_text(data)

    def path_write_bytes(self, path: PurePosixPath | MontyFileHandle, data: bytes) -> int:
        return self._path(path, write=True).write_bytes(data)

    def path_mkdir(self, path: PurePosixPath, parents: bool, exist_ok: bool) -> None:
        self._path(path, write=True).mkdir(parents=parents, exist_ok=exist_ok)

    def path_unlink(self, path: PurePosixPath) -> None:
        self._path(path, write=True).unlink()

    def path_rmdir(self, path: PurePosixPath) -> None:
        self._path(path, write=True).rmdir()

    def path_iterdir(self, path: PurePosixPath) -> list[PurePosixPath]:
        directory = self._path(path)
        return [
            PurePosixPath(child.as_posix())
            for child in directory.iterdir()
            if not is_secret_path(child, home=self.home)
        ]

    def path_stat(self, path: PurePosixPath) -> StatResult:
        value = self._path(path).stat()
        return StatResult(*value[:10])

    def path_rename(self, path: PurePosixPath, target: PurePosixPath) -> None:
        source = self._path(path, write=True)
        destination = self._path(target, write=True)
        source.rename(destination)

    def path_resolve(self, path: PurePosixPath) -> str:
        return str(self._path(path))

    def path_absolute(self, path: PurePosixPath) -> str:
        lexical = self._lexical(path).absolute()
        if is_secret_path(lexical, home=self.home):
            raise PermissionError(f"Credential/secret path is blocked: {lexical}")
        return str(lexical)

    def getenv(self, key: str, default: str | None = None) -> str | None:
        return default

    def get_environ(self) -> dict[str, str]:
        return {}
