"""Verify built distributions before they are published to an index.

Two things go wrong silently enough to be worth a hard gate:

1. `uv-dynamic-versioning` derives the version from git history. Under a shallow
   checkout the tags and `tag-branch` are missing, so it falls back to
   `fallback-version` *without* erroring -- happily building 0.0.0 for a v1.2.3
   release. A version published to PyPI can never be reused, so a wrong number
   is unrecoverable.
2. Builds off a tag carry PEP 440 local metadata (`+branch.sha.dirty`). Neither
   PyPI nor TestPyPI accepts a local version, so this fails at upload time with
   a far less obvious error than it does here.

Exits non-zero with an explanation rather than letting either reach the index.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from packaging.utils import parse_sdist_filename, parse_wheel_filename
from packaging.version import Version

DIST = Path("dist")


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def main() -> None:
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))

    if len(wheels) != 1 or len(sdists) != 1:
        fail(
            f"expected exactly one wheel and one sdist in {DIST}/, found "
            f"{len(wheels)} wheel(s) and {len(sdists)} sdist(s): "
            f"{[p.name for p in (*wheels, *sdists)]}"
        )

    _, wheel_version, _, _ = parse_wheel_filename(wheels[0].name)
    _, sdist_version = parse_sdist_filename(sdists[0].name)

    if wheel_version != sdist_version:
        fail(f"wheel version {wheel_version} != sdist version {sdist_version}")

    version = wheel_version
    print(f"built version: {version}")

    if version.local is not None:
        fail(
            f"version {version} carries local metadata (+{version.local}), which no "
            "package index accepts. Build from a tagged, clean checkout."
        )

    tag = os.environ.get("RELEASE_TAG", "").strip()
    if not tag:
        print("RELEASE_TAG unset; skipping tag comparison (manual/TestPyPI run).")
        return

    try:
        expected = Version(tag[1:] if tag.startswith("v") else tag)
    except Exception:
        fail(f"release tag {tag!r} is not a valid PEP 440 version")
        return

    # Compare parsed Versions so equivalent spellings (1.0 vs 1.0.0, rc1 vs RC1)
    # do not trip the gate.
    if version != expected:
        fail(
            f"built version {version} does not match release tag {tag} "
            f"(expected {expected}). This usually means the checkout lacked full "
            "git history, so the version fell back instead of deriving from the tag."
        )

    print(f"version {version} matches release tag {tag}")


if __name__ == "__main__":
    main()
