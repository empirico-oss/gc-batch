"""Fail the build if a runtime dependency carries a license gc-batch cannot ship.

gc-batch is distributed under the MIT license, so every package in its runtime
closure must be permissive (MIT / BSD / Apache-2.0 / ISC / PSF / Unlicense /
public domain). Strong copyleft (GPL, LGPL, AGPL) is rejected outright. Weak,
file-level copyleft (MPL, EPL, CDDL) is rejected unless the package is listed in
``ALLOWED_WEAK_COPYLEFT`` below, so adopting one is a deliberate, reviewed act
rather than an accident.

The check is fail-closed: a license this script cannot classify is an error, not
a pass. Add the package to an allowlist once a human has read its terms.

Run against a runtime-only environment -- dev and docs dependencies do not ship
and are out of scope:

    uv run --frozen --no-dev python scripts/check_licenses.py
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions

# Packages whose own metadata is unreliable or absent upstream, pinned to the
# license published in their repository. Keep this list as short as possible.
LICENSE_OVERRIDES: dict[str, str] = {}

# Weak / file-level copyleft that is acceptable to redistribute unmodified.
# Each entry is a conscious decision: the obligations attach to that package's
# own files, not to gc-batch, as long as we ship it as an unmodified dependency.
ALLOWED_WEAK_COPYLEFT: dict[str, str] = {
    # The CA bundle. MPL-2.0 is per-file copyleft and we never patch certifi,
    # so nothing propagates to gc-batch. Ubiquitous in the Python HTTP stack.
    "certifi": "MPL-2.0",
}

# Distributions that are not third-party dependencies.
SELF = {"gc-batch", "gc_batch"}

# Matched in order: strong copyleft wins over everything so that a dual license
# such as "GPL-2.0 OR MIT" is surfaced rather than silently passed.
STRONG_COPYLEFT = re.compile(
    r"\b(?:a|l)?gpl(?:v?[0-9]|-)?"
    r"|\bgnu\s+(?:lesser\s+|affero\s+)?general\s+public"
    r"|\bgeneral\s+public\s+license"
    r"|\bsleepycat\b"
    r"|\bopen\s+software\s+license\b|\bosl-[0-9]"
    r"|\bcecill(?!-b|-c)"
    r"|\beupl\b",
    re.IGNORECASE,
)

WEAK_COPYLEFT = re.compile(
    r"\bmpl\b|\bmozilla\s+public\s+license"
    r"|\bepl\b|\beclipse\s+public\s+license"
    r"|\bcddl\b|\bcommon\s+development\s+and\s+distribution"
    r"|\bms-rl\b|\bmicrosoft\s+reciprocal"
    r"|\bartistic\b",
    re.IGNORECASE,
)

PERMISSIVE = re.compile(
    r"\bmit\b|\bmit\s+license\b|\bexpat\b"
    r"|\bbsd\b"
    r"|\bapache\b"
    r"|\bisc\b|\biscl\b"
    r"|\bpsf\b|\bpython\s+software\s+foundation"
    r"|\bunlicense\b|\bpublic\s+domain\b|\bcc0\b"
    r"|\bzlib\b|\bzope\s+public\b|\bzpl\b"
    r"|\bapache\s+software\s+license\b",
    re.IGNORECASE,
)

# A License: field holding the whole license text tells us nothing a regex can
# trust -- full texts mention other licenses. Treat long values as absent.
MAX_LEGACY_LICENSE_LEN = 200


def resolve_license(dist) -> tuple[str, str]:
    """Return ``(license_text, source)`` for a distribution, best source first.

    PEP 639 ``License-Expression`` is authoritative when present. Trove
    classifiers come next. The legacy free-text ``License`` field is the last
    resort and only when it is short enough to be an identifier, not a text dump.
    """
    meta = dist.metadata
    name = meta["Name"] or ""

    if override := LICENSE_OVERRIDES.get(canonical(name)):
        return override, "override"

    if expression := (meta.get("License-Expression") or "").strip():
        return expression, "License-Expression"

    classifiers = [
        classifier.split("::")[-1].strip()
        for classifier in meta.get_all("Classifier") or []
        if classifier.startswith("License ::")
    ]
    if classifiers:
        return " OR ".join(classifiers), "classifier"

    legacy = " ".join((meta.get("License") or "").split())
    if legacy and len(legacy) <= MAX_LEGACY_LICENSE_LEN:
        return legacy, "License"

    return "", "missing"


def canonical(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def classify(name: str, license_text: str) -> tuple[str, str]:
    """Return ``(verdict, reason)`` where verdict is ok, deny, or unknown."""
    if not license_text:
        return "unknown", "no license metadata"

    if STRONG_COPYLEFT.search(license_text):
        return "deny", "strong copyleft (GPL family) cannot ship under MIT"

    if WEAK_COPYLEFT.search(license_text):
        allowed = ALLOWED_WEAK_COPYLEFT.get(canonical(name))
        if allowed:
            return "ok", f"weak copyleft, reviewed and allowed as {allowed}"
        return "deny", "weak copyleft not in ALLOWED_WEAK_COPYLEFT"

    if PERMISSIVE.search(license_text):
        return "ok", "permissive"

    return "unknown", "license not recognized by this check"


def main() -> int:
    results = []
    for dist in distributions():
        name = dist.metadata["Name"]
        if not name or canonical(name) in {canonical(s) for s in SELF}:
            continue
        license_text, source = resolve_license(dist)
        verdict, reason = classify(name, license_text)
        results.append((canonical(name), dist.version, license_text, source, verdict, reason))

    results.sort()

    width = max((len(row[0]) for row in results), default=10)
    for name, version, license_text, source, verdict, _ in results:
        mark = {"ok": "ok  ", "deny": "DENY", "unknown": "????"}[verdict]
        print(f"{mark}  {name:<{width}}  {version:<12}  {license_text or '-'}  [{source}]")

    problems = [row for row in results if row[4] != "ok"]
    print(f"\n{len(results)} runtime package(s) checked, {len(problems)} problem(s).")

    if not problems:
        print("No copyleft licenses found in the runtime dependency closure.")
        return 0

    print("\nProblems:", file=sys.stderr)
    for name, version, license_text, _, _verdict, reason in problems:
        print(f"  {name} {version}: {license_text or '<none>'} -- {reason}", file=sys.stderr)
    print(
        "\nResolve by dropping the dependency, or -- if the terms are genuinely "
        "compatible with MIT redistribution -- recording it in "
        "ALLOWED_WEAK_COPYLEFT or LICENSE_OVERRIDES in scripts/check_licenses.py.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
