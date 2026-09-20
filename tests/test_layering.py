"""
Import-layering rules, checked from the source rather than trusted to review.

CLAUDE.md's Architecture Rule 2 (phases build on earlier phases only) and the
specific rule "``jalraksha.impact`` must not import ``jalraksha.gee``" were
written down in docstrings and never tested. The practical payoff of the rule
is not purity: impact code that imports no Earth Engine layer stays testable
with no network and no credentials, which is what keeps it in CI. damage.py
receives its built-up and cropland arrays from tasks.py for exactly that reason.

The rules are an explicit list of FORBIDDEN edges, so a later package
(hydrology, safety) adds a line here rather than a new mechanism. Imports are
read with ``ast``, including imports inside functions: a lazy import is still
a dependency, it is just one that fails later.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "jalraksha"

# (importing package prefix, forbidden imported prefix, why)
FORBIDDEN = [
    ("jalraksha", "jalraksha_service",
     "the service depends on the library, never the reverse"),
    ("jalraksha.impact", "jalraksha.gee",
     "Phase 6 must not reach into Phase 9; the service fetches and passes arrays"),
    ("jalraksha.solver", "jalraksha.export",
     "the solver returns results; exporting them is a later phase"),
    ("jalraksha.solver", "jalraksha.impact",
     "the solver must not depend on consequence analysis"),
    ("jalraksha.solver", "jalraksha.gee",
     "the solver must run offline"),
    ("jalraksha.export", "jalraksha.gee",
     "an export writes what a run recorded; it must not fetch anything"),
    ("jalraksha.presets", "jalraksha.",
     "presets.py is Phase 0 data and imports nothing else from jalraksha"),
]


# Violations that existed when this test was written, recorded rather than
# silently allowed, so the rule stays live for every other module. Each entry is
# (importing module, forbidden prefix) -> why it is still there. Fixing one means
# deleting its line; adding one needs a reason a reviewer can argue with.
KNOWN_VIOLATIONS = {
    ("jalraksha.cli", "jalraksha_service"):
        "the CLI registers its runs in the service database so the dashboard "
        "can list them; pre-existing, predates this test",
}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> Iterator[Tuple[str, int]]:
    """Every absolute module name `path` imports, with its line number."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            yield name, node.lineno
            # `from jalraksha import gee` imports a package by its alias name.
            for alias in node.names:
                yield f"{name}.{alias.name}", node.lineno


def _library_files():
    return sorted(p for p in LIBRARY.rglob("*.py") if "__pycache__" not in p.parts)


def _matches(name: str, prefix: str) -> bool:
    if prefix.endswith("."):
        return name.startswith(prefix)
    return name == prefix or name.startswith(prefix + ".")


@pytest.mark.parametrize("importer,forbidden,why", FORBIDDEN,
                         ids=[f"{a}-x-{b}" for a, b, _ in FORBIDDEN])
def test_forbidden_import_edges(importer, forbidden, why):
    violations = []
    for path in _library_files():
        module = _module_name(path)
        if not _matches(module, importer):
            continue
        if (module, forbidden) in KNOWN_VIOLATIONS:
            continue
        for name, line in _imports(path):
            if _matches(name, forbidden):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line} imports {name}")
    assert not violations, f"{importer} must not import {forbidden} ({why}):\n" + "\n".join(violations)


def test_the_rules_are_live():
    """A typo in a prefix would make a rule pass vacuously; each must match files."""
    modules = [_module_name(p) for p in _library_files()]
    for importer, _forbidden, _why in FORBIDDEN:
        assert any(_matches(m, importer) for m in modules), importer


def test_known_violations_are_still_real():
    """An exception that no longer applies must be deleted, not left to rot."""
    for (module, forbidden), _why in KNOWN_VIOLATIONS.items():
        path = LIBRARY.parent / (module.replace(".", "/") + ".py")
        assert any(_matches(name, forbidden) for name, _line in _imports(path)), (
            f"{module} no longer imports {forbidden}; remove it from KNOWN_VIOLATIONS"
        )
