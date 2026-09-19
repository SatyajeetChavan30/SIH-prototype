"""
Python 3.14 compatibility for compyle, the code generator behind PySPH's GPU
backends.

WHY THIS EXISTS. Python deprecated the per-type AST constant nodes in 3.8 and
REMOVED them in 3.14. compyle 0.9.1 predates that removal and breaks in two
different ways, one loud and one silent:

  1. LOUD. It asks `isinstance(node, ast.Str)` and then reads `node.s` at four
     places -- `jit.py` (`visit_declare`, `visit_cast`) and `translator.py`
     (`_remove_docstring`, `visit_Assign`). The first GPU kernel PySPH generates
     dies with "module 'ast' has no attribute 'Str'".
  2. SILENT, AND WORSE. Its visitors are named for the removed node types:
     `CConverter.visit_Num` / `visit_Str` / `visit_NameConstant` and
     `AnnotationHelper.visit_Num`. A literal now parses to `ast.Constant`, and
     `NodeVisitor` dispatches on the node's type name, so those methods are never
     called. Control falls to `generic_visit`, which returns None, and the
     generated OpenCL contains the word None where every number should be:

         r = ((r | (r << None)) & None);
         key = interleave3(c[None], c[None], c[None]);

     That is a compile error here, which is lucky. The same class of defect in a
     code path that happened to accept it would have produced a kernel that ran
     and computed nonsense.

compyle 0.9.1 is the latest release on PyPI, so there is nothing to upgrade to
and the repair has to be local.

WHAT IS RESTORED, AND WITH WHAT SEMANTICS. Exactly what CPython and compyle used
to provide between them, no more:

  * `ast.Str`, whose `isinstance()` is true only for an `ast.Constant` holding a
    `str`. CPython implemented that with a metaclass `__instancecheck__` and a
    `_const_types` table whose entry for `Str` was `(str,)`. A looser shim that
    matched any `Constant` would make compyle accept `declare(3)` and then fail
    further in, with a worse message than it has now.
  * `ast.Constant.n` and `.s`, the read aliases for `.value`, which the legacy
    visitors above still use. CPython set these as plain properties on the class.
  * a `visit_Constant` on each compyle visitor, dispatching by the value's type
    to whichever legacy method that class defines. The order matters: `True`,
    `False` and `None` were `NameConstant`, never `Num`, and `bool` is a subclass
    of `int`, so booleans must be tested first.

WHAT IS NOT RESTORED, AND WHY THAT IS RIGHT. PySPH's own GPU helper
(`sph/acceleration_eval_gpu_helper.py`) also has a dead `visit_Num`, in a
`NodeTransformer` that rewrites a numeric literal into a STRING constant holding
its float32 spelling. Reviving that one would be actively wrong here: on the
`--use-double` path `literal_to_float(value, use_double=True)` returns
`str(value)` unchanged, so the transform is the identity, and forcing it would
put a quoted "1.5" into the generated C. Left dead it is a no-op, and
`CConverter.visit_Num` -- which this module does revive -- applies the float32
suffix itself when it is wanted. This is why the GPU path always passes
`--use-double` rather than treating it as a preference.

SCOPE. Everything is installed by a context manager and undone in its `finally`,
so it exists only while PySPH compiles. While held, the `ast` part is a
process-wide change: a library that tests `hasattr(ast, "Str")` to detect an old
Python would take the wrong branch inside that window. Two things keep that
acceptable -- SPH runs in the run subprocess rather than in the API server, and
the window is a single `app.run()` call.
"""

from __future__ import annotations

import ast
import contextlib
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

#: AST names this module can put back, for `isinstance` checks in compyle's
#: source. `pysph_runner._compyle_gpu_incompatibility` subtracts these from the
#: removed names it finds, so breakage this shim does NOT repair still refuses
#: the GPU instead of being assumed fine.
RESTORED_AST_NAMES: Tuple[str, ...] = ("Str",)

#: compyle visitors whose constant handling 3.14 silenced. Subclasses
#: (OpenCLConverter, CUDAConverter, the JIT helpers) inherit the repair.
_VISITOR_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("compyle.translator", "CConverter"),
    ("compyle.jit", "AnnotationHelper"),
)

#: Value type -> the legacy visitor that used to receive it. Booleans and None
#: were NameConstant; bool is a subclass of int, so it is matched first.
_LEGACY_BY_VALUE: Tuple[Tuple[Any, str], ...] = (
    (bool, "visit_NameConstant"),
    (type(None), "visit_NameConstant"),
    (str, "visit_Str"),
    (bytes, "visit_Bytes"),
    ((int, float, complex), "visit_Num"),
)

_MISSING = object()


class _ConstantAliasMeta(type):
    """
    isinstance() for a deprecated constant alias, the way CPython did it.

    The alias is not a real node type -- every literal parses to `ast.Constant`
    -- so membership is decided by the type of the constant's value.
    """

    def __instancecheck__(cls, instance) -> bool:  # noqa: N805
        if not isinstance(instance, ast.Constant):
            return False
        try:
            value = instance.value
        except AttributeError:
            return False
        return isinstance(value, cls.value_types)


class _Str(ast.Constant, metaclass=_ConstantAliasMeta):
    """Stand-in for the removed `ast.Str`: a Constant whose value is a str."""

    _fields = ("s",)
    value_types: Tuple[type, ...] = (str,)


def _legacy_visitor_name(value: Any) -> str:
    """Which removed node type a constant value used to parse as."""
    for types, name in _LEGACY_BY_VALUE:
        if isinstance(value, types):
            return name
    return "visit_Num"


def _visit_constant(self, node):
    """
    Dispatch `ast.Constant` to the legacy per-type visitor, as 3.7 would have.

    Falls back to `generic_visit` only when the class defines no legacy handler
    at all, which `visitor_repair_gaps()` reports up front so it cannot happen
    silently.
    """
    handler = getattr(type(self), _legacy_visitor_name(node.value), None)
    if handler is None:
        return self.generic_visit(node)
    return handler(self, node)


def _visitor_classes() -> List[type]:
    """The compyle visitor classes present in this installation."""
    import importlib

    classes: List[type] = []
    for module_name, class_name in _VISITOR_TARGETS:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # compyle absent or broken; the caller reports that
            continue
        cls = getattr(module, class_name, None)
        if isinstance(cls, type):
            classes.append(cls)
    return classes


def visitor_repair_gaps() -> List[str]:
    """
    compyle visitors this module cannot repair, as human-readable reasons.

    A class is fine if it already handles `ast.Constant` itself (a fixed compyle,
    which this module then leaves alone) or if it still defines at least one
    legacy handler to dispatch to. A class with neither would silently emit
    `None` for literals, so it is reported as a blocker rather than patched
    hopefully.
    """
    gaps: List[str] = []
    for cls in _visitor_classes():
        if "visit_Constant" in vars(cls):
            continue
        legacy = [name for _, name in _LEGACY_BY_VALUE if getattr(cls, name, None)]
        if not legacy:
            gaps.append(
                f"compyle's {cls.__module__}.{cls.__name__} has neither "
                f"visit_Constant nor any legacy constant visitor, so numeric "
                f"literals would be generated as None"
            )
    return gaps


@contextlib.contextmanager
def restored_ast_aliases() -> Iterator[None]:
    """
    Put `ast.Str`, `ast.Constant.n` and `ast.Constant.s` back for this block.

    Reversible and nestable: whatever was there before is restored on exit, so a
    real future `ast.Str` is preserved rather than clobbered.
    """
    previous_str = getattr(ast, "Str", _MISSING)
    previous_aliases = {name: vars(ast.Constant).get(name, _MISSING) for name in ("n", "s")}

    ast.Str = _Str
    for name, previous in previous_aliases.items():
        if previous is _MISSING:
            # Exactly CPython's pre-3.12 definition: a property aliasing .value.
            setattr(
                ast.Constant,
                name,
                property(
                    lambda self: self.value,
                    lambda self, value: setattr(self, "value", value),
                ),
            )
    try:
        yield
    finally:
        if previous_str is _MISSING:
            try:
                del ast.Str
            except AttributeError:  # pragma: no cover - removed by someone else
                pass
        else:
            ast.Str = previous_str
        for name, previous in previous_aliases.items():
            if previous is _MISSING:
                try:
                    delattr(ast.Constant, name)
                except AttributeError:  # pragma: no cover
                    pass
            else:
                setattr(ast.Constant, name, previous)


@contextlib.contextmanager
def restored_constant_visitors() -> Iterator[None]:
    """
    Give compyle's visitors a `visit_Constant` for this block.

    Leaves alone any class that already has its own, so a fixed compyle is not
    overridden by this one.
    """
    patched: List[type] = []
    try:
        for cls in _visitor_classes():
            if "visit_Constant" in vars(cls):
                continue
            cls.visit_Constant = _visit_constant
            patched.append(cls)
        yield
    finally:
        for cls in patched:
            try:
                del cls.visit_Constant
            except AttributeError:  # pragma: no cover
                pass


@contextlib.contextmanager
def compyle_python314_compat() -> Iterator[None]:
    """Both repairs at once: what a PySPH GPU compile needs on Python 3.14."""
    with restored_ast_aliases(), restored_constant_visitors():
        yield


def compyle_python314_compat_if(enabled: bool):
    """
    `compyle_python314_compat()` when `enabled`, otherwise a no-op context.

    Lets a caller hold the patches for the GPU path only: PySPH's CPU backend
    generates Cython by a different route and needs none of this, and a patch
    nobody needs should not be installed.
    """
    return compyle_python314_compat() if enabled else contextlib.nullcontext()
