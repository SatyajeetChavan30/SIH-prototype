"""
Resolve every `path:line` citation in a Markdown document against the worktree.

The Technical Reference Manual carries roughly 2,500 such citations. They are
the manual's whole claim to being checkable, and they rot silently: a file is
renamed, a function moves down 200 lines, and the prose still reads as if it
were verified. Nothing failed, so nothing said so.

Four verdicts:

    OK          the file exists and the cited line is inside it
    FILE_GONE   no tracked file matches the cited path
    LINE_OOR    the file exists; the line number is past its end
    AMBIGUOUS   the citation is a bare basename that several tracked files
                could satisfy (`main.py` exists in three trees)

AMBIGUOUS is a real defect, not a limitation of this script. A citation a
reader cannot resolve without guessing which `main.py` was meant is not a
citation. The repair is to widen it in the document to a repo-relative path,
which is why the default is to fail on it like any other status.

Usage:
    python tools/check_citations.py                     # the manual, summary only
    python tools/check_citations.py --csv out.csv       # full table
    python tools/check_citations.py --status FILE_GONE  # one status, as a worklist
    python tools/check_citations.py docs/other.md
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_DOCUMENT = Path("docs/JalRaksha_Technical_Reference_Manual.md")

# Source extensions worth resolving. Prose cites plenty of other things
# (`.tif`, `.nc`, `.pvsm`) that are build products rather than tracked files,
# and treating their absence as a defect would drown the real hits.
SOURCE_SUFFIXES = ("py", "jsx", "js", "md", "json", "yaml", "yml", "toml", "html")

# A backtick-quoted path with a line number or line range: `run.py:515-518`.
# Only backticked citations count. Bare prose like "see run.py line 515" is
# unresolvable by construction and is not what this file is checking.
#
# `path@<commit>:line` cites code as it stood at that commit. A defect register
# has to be able to describe code that was DELETED — "PopulationEstimator
# returned zero for every input" is a claim about something no longer on disk,
# and dropping the citation to make a checker pass would destroy the evidence
# for a finding rather than verify it. Pinned citations are resolved with
# `git show`, so they stay checkable forever.
CITATION = re.compile(
    r"`(?P<path>[A-Za-z0-9_./-]+\.(?:" + "|".join(SOURCE_SUFFIXES) + r"))"
    r"(?:@(?P<commit>[0-9a-f]{7,40}))?"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?`"
)

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def tracked_files() -> list[str]:
    """Every file git tracks, as forward-slash repo-relative paths."""
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def build_suffix_index(paths: list[str]) -> dict[str, list[str]]:
    """
    Map every trailing path fragment to the tracked files that end with it.

    `sar.py`, `gee/sar.py` and `jalraksha/gee/sar.py` all resolve to the same
    file; only the first is ambiguous, and only if some other tree also has a
    `sar.py`. Indexing every suffix rather than only the basename is what lets
    a partially-qualified citation resolve without being widened all the way.
    """
    index: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        parts = path.split("/")
        for i in range(len(parts)):
            index["/".join(parts[i:])].append(path)
    # An exact repo-relative path is never ambiguous, whatever else ends with
    # it. `README.md` means the one at the root; the four other READMEs are
    # reachable only by writing `paraview/README.md` and so on.
    for path in paths:
        index[path] = [path]
    return index


def line_counts(paths: set[str]) -> dict[str, int]:
    counts = {}
    for path in paths:
        try:
            with open(path, "rb") as handle:
                counts[path] = sum(1 for _ in handle)
        except OSError:
            counts[path] = 0
    return counts


_PINNED: dict[tuple[str, str], int | None] = {}


def pinned_line_count(commit: str, path: str) -> int | None:
    """Lines in `path` as of `commit`, or None if it did not exist there."""
    key = (commit, path)
    if key not in _PINNED:
        result = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        _PINNED[key] = len(result.stdout.splitlines()) if result.returncode == 0 else None
    return _PINNED[key]


def nearest_heading(headings: list[tuple[int, str]], line_no: int) -> str:
    """The last heading at or above `line_no`, for locating a finding by eye."""
    found = ""
    for heading_line, text in headings:
        if heading_line > line_no:
            break
        found = text
    return found


def check(document: Path) -> list[dict[str, str]]:
    index = build_suffix_index(tracked_files())
    lines = document.read_text(encoding="utf-8").splitlines()

    headings: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        match = HEADING.match(line)
        if match:
            headings.append((i, match.group(2).strip()))

    findings: list[dict[str, str]] = []
    wanted: set[str] = set()
    raw: list[tuple[int, str, str, int, int, list[str]]] = []

    for line_no, line in enumerate(lines, start=1):
        for match in CITATION.finditer(line):
            cited = match.group("path")
            commit = match.group("commit") or ""
            start = int(match.group("start"))
            end = int(match.group("end") or start)
            candidates = index.get(cited, [])
            raw.append((line_no, cited, commit, start, end, candidates))
            if not commit:
                wanted.update(candidates)

    counts = line_counts(wanted)

    for line_no, cited, commit, start, end, candidates in raw:
        span = f"{start}" if start == end else f"{start}-{end}"
        citation = f"{cited}@{commit}:{span}" if commit else f"{cited}:{span}"
        record = {
            "doc_line": str(line_no),
            "citation": citation,
            "resolved": "",
            "file_lines": "",
            "status": "",
            "section": nearest_heading(headings, line_no),
        }
        if commit:
            total = pinned_line_count(commit, cited)
            record["resolved"] = f"{cited} @ {commit}"
            if total is None:
                record["status"] = "FILE_GONE"
            else:
                record["file_lines"] = str(total)
                record["status"] = "OK" if end <= total else "LINE_OOR"
        elif not candidates:
            record["status"] = "FILE_GONE"
        elif len(candidates) > 1:
            record["status"] = "AMBIGUOUS"
            record["resolved"] = " | ".join(sorted(candidates))
        else:
            resolved = candidates[0]
            total = counts[resolved]
            record["resolved"] = resolved
            record["file_lines"] = str(total)
            record["status"] = "OK" if end <= total else "LINE_OOR"
        findings.append(record)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", default=str(DEFAULT_DOCUMENT))
    parser.add_argument("--csv", help="Write the full table here.")
    parser.add_argument(
        "--status",
        action="append",
        choices=["OK", "FILE_GONE", "LINE_OOR", "AMBIGUOUS"],
        help="Print only these statuses. Repeatable.",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        choices=["FILE_GONE", "LINE_OOR", "AMBIGUOUS"],
        help="Do not fail on this status. Repeatable, for a staged cleanup.",
    )
    args = parser.parse_args()

    document = Path(args.document)
    if not document.exists():
        print(f"No such document: {document}", file=sys.stderr)
        return 2

    findings = check(document)
    tally: dict[str, int] = defaultdict(int)
    for record in findings:
        tally[record["status"]] += 1

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["doc_line", "citation", "resolved", "file_lines", "status", "section"],
            )
            writer.writeheader()
            writer.writerows(findings)
        print(f"Wrote {len(findings)} rows to {args.csv}")

    if args.status:
        wanted = set(args.status)
        for record in findings:
            if record["status"] in wanted:
                print(
                    f"{document}:{record['doc_line']}  {record['status']:<10}"
                    f"  {record['citation']}"
                    + (f"  -> {record['resolved']}" if record["resolved"] else "")
                )

    unique_citations = len({record["citation"] for record in findings})
    print(
        f"\n{document}: {len(findings)} citations ({unique_citations} unique)  "
        + "  ".join(f"{status}={tally[status]}" for status in sorted(tally))
    )

    failing = {"FILE_GONE", "LINE_OOR", "AMBIGUOUS"} - set(args.allow)
    broken = sum(tally[status] for status in failing)
    if broken:
        print(f"{broken} citation(s) do not resolve.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
