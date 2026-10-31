"""The disposable workspace: containment, file identities, and the model files it holds.

Every path a write touches must lie inside CREO_CLI_WORKSPACE, which a person sets. No
symlinks or junctions anywhere in the path, no network paths, no parent traversal.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from .core import Error

MAX_ARTIFACT = 256 * 1024 * 1024
MODEL_FILE = re.compile(r"([A-Za-z][A-Za-z0-9_-]{0,30})\.(prt|asm|drw)(?:\.([0-9]{1,6}))?", re.I)
KINDS = {"prt": "part", "asm": "assembly", "drw": "drawing"}


def workspace() -> Path:
    raw = os.environ.get("CREO_CLI_WORKSPACE")
    if not raw:
        raise Error(
            "E_CONFIG",
            "writes need CREO_CLI_WORKSPACE pointing to a disposable local directory",
            {
                "fix": "a person sets CREO_CLI_WORKSPACE to an existing directory without symlinks "
                "or junctions"
            },
        )
    p = Path(raw).expanduser().absolute()
    if not p.is_dir():
        raise Error("E_CONFIG", "CREO_CLI_WORKSPACE is not an existing directory")
    no_links(p)
    return p.resolve()


def no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise Error("E_FORBIDDEN", "workspace paths must not use symlinks or junctions")


def contained(value: str, *, directory: bool | None = None, exists: bool = True) -> Path:
    """A path inside the workspace, resolved; relative paths are taken from its root."""
    root = workspace()
    if value.startswith(("\\\\", "//")) or ".." in value.replace("\\", "/").split("/"):
        raise Error("E_FORBIDDEN", "network paths and parent traversal are not permitted")
    p = Path(value).expanduser()
    p = (p if p.is_absolute() else root / p).absolute()
    no_links(p)
    p = p.resolve()
    if not p.is_relative_to(root):
        raise Error(
            "E_FORBIDDEN",
            "path is outside the workspace",
            {"path": str(p), "workspace": str(root), "_untrusted": ["path"]},
        )
    if exists and not p.exists():
        raise Error(
            "E_NOT_FOUND",
            "no such file or directory in the workspace",
            {"path": str(p), "_untrusted": ["path"]},
        )
    if exists and directory is not None and (not p.is_dir() if directory else not p.is_file()):
        raise Error(
            "E_VALIDATION",
            "expected a directory" if directory else "expected a file",
            {"path": str(p), "_untrusted": ["path"]},
        )
    return p


def artifact(path: Path, *, identity: bool = False) -> dict:
    """A file's identity: path, size and SHA-256, read without following links."""
    no_links(path)
    try:
        fd = os.open(
            path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        h, size = hashlib.sha256(), 0
        with os.fdopen(fd, "rb") as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARTIFACT:
                raise Error(
                    "E_VALIDATION",
                    "expected a regular file no larger than 256 MiB",
                    {"path": str(path)},
                )
            while block := f.read(1024 * 1024):
                h.update(block)
                size += len(block)
                if size > MAX_ARTIFACT:
                    raise Error("E_VALIDATION", "file grew past 256 MiB", {"path": str(path)})
            after = os.fstat(f.fileno())
        latest = path.stat()

        def stamp(s):
            return (s.st_size, s.st_mtime_ns, s.st_ino)

        if stamp(before) != stamp(after) or stamp(after) != stamp(latest):
            raise Error("E_CONFLICT", "file changed while it was read", {"path": str(path)})
        result = {"path": str(path), "size_bytes": size, "sha256": h.hexdigest()}
        if identity:
            result["file_identity"] = [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns]
        return result
    except OSError as exc:
        raise Error(
            "E_IO", "cannot read file", {"path": str(path), "_untrusted": ["path"]}
        ) from exc


def version(path: str | Path) -> int:
    """block.prt.3 -> 3; block.prt -> 0; not a model file -> -1."""
    m = MODEL_FILE.fullmatch(Path(path).name)
    return int(m[3] or 0) if m else -1


def model_files(directory: Path, filename: str, *, identity: bool = False) -> list[dict]:
    """Every version of one model file in a directory, with its identity, oldest first."""
    pattern = re.compile(re.escape(filename) + r"(?:\.[0-9]+)?", re.I)
    matches = []
    try:
        with os.scandir(directory) as entries:
            for n, entry in enumerate(entries):
                if n >= 20000:
                    raise Error(
                        "E_VALIDATION",
                        "directory holds more than 20000 entries",
                        {"path": str(directory)},
                    )
                if pattern.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                    matches.append(artifact(Path(entry.path), identity=identity))
                    if len(matches) > 100:
                        raise Error(
                            "E_VALIDATION",
                            "more than 100 versions of one model",
                            {"model": filename},
                        )
    except OSError as exc:
        raise Error("E_IO", "cannot list the directory", {"path": str(directory)}) from exc
    return sorted(matches, key=lambda x: version(x["path"]))


def list_models(kind: str | None = None, name: str | None = None) -> list[dict]:
    """Model files under the workspace, one row per model with its versions. Bounded walk."""
    root = workspace()
    rows: dict[tuple[str, str], dict] = {}
    seen = 0
    for directory, dirs, files in os.walk(root):
        here = Path(directory)
        depth = len(here.relative_to(root).parts)
        dirs[:] = sorted(
            d for d in dirs if not d.startswith(".") and depth < 4 and not (here / d).is_symlink()
        )
        for file in files:
            seen += 1
            if seen > 50000:
                raise Error(
                    "E_VALIDATION", "the workspace holds more than 50000 files; list a narrower one"
                )
            m = MODEL_FILE.fullmatch(file)
            if not m:
                continue
            model = m[1].lower() + "." + m[2].lower()
            model_kind = KINDS[m[2].lower()]
            if kind and model_kind != kind or name and name.casefold() not in model.casefold():
                continue
            relative = here.relative_to(root).as_posix() or "."
            row = rows.setdefault(
                (relative, model),
                {"model": model, "kind": model_kind, "directory": relative, "versions": []},
            )
            row["versions"].append(int(m[3] or 0))
    out = []
    for (relative, model), row in rows.items():
        row["versions"].sort()
        newest = f"{model}.{row['versions'][-1]}" if row["versions"][-1] else model
        path = root / relative / newest
        try:
            info = path.stat()
            row |= {
                "newest": newest,
                "size_bytes": info.st_size,
                "modified_at": datetime.fromtimestamp(info.st_mtime, UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            }
        except OSError:
            row |= {"newest": newest, "size_bytes": None, "modified_at": None}
        out.append(row)
    return sorted(out, key=lambda r: (r["directory"], r["model"]))
