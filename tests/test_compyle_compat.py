"""
Tests for the Python 3.14 repair of compyle, PySPH's GPU code generator.

These tests exist because the defect they guard was SILENT. Python 3.14 removed
`ast.Str`, `ast.Num` and the `.s`/`.n` aliases; compyle 0.9.1's constant visitors
are still named for those node types, so `NodeVisitor` stopped dispatching to
them, `generic_visit` returned None, and the generated OpenCL read

    r = ((r | (r << None)) & None);

Here that was a compile error. In a code path that accepted it, it would have
been a kernel that ran and computed nonsense. So the tests below check the two
things that distinguish a working repair from a plausible one: that the shim's
`isinstance` is as NARROW as CPython's was (str only, not "any constant"), and
that real compyle source — not a hand-built AST — is translated with its
literals intact.

Every patch must also be gone after the context manager exits: while held, the
`ast` half is a process-wide change, and a library that probes
`hasattr(ast, "Str")` to detect an old Python would take the wrong branch.
"""

import ast

import pytest

from jalraksha.sph.compyle_compat import (
    RESTORED_AST_NAMES,
    compyle_python314_compat,
    compyle_python314_compat_if,
    restored_ast_aliases,
    restored_constant_visitors,
    visitor_repair_gaps,
)

try:  # compyle is installed with PySPH; absent, only the ast half is testable
    import compyle.jit as compyle_jit
    import compyle.translator as compyle_translator
    from compyle.types import annotate

    COMPYLE_OK, COMPYLE_DETAIL = True, ""
except Exception as exc:  # pragma: no cover - depends on the environment
    compyle_jit = compyle_translator = None

    def annotate(**kw):  # the decorated kernels below are never reached
        return lambda func: func

    COMPYLE_OK, COMPYLE_DETAIL = False, f"{type(exc).__name__}: {exc}"

requires_compyle = pytest.mark.skipif(
    not COMPYLE_OK, reason=f"compyle unavailable: {COMPYLE_DETAIL}")


# Kernels for the translation tests. They are module-level because compyle reads
# them with inspect.getsource, which cannot see a function defined in a method
# body of a dynamically executed module, and annotated because an untyped
# argument raises CodeGenerationError("Unknown type") before any constant is
# visited -- i.e. before the thing under test runs at all.

@annotate(i='int', return_='int')
def _shift_kernel(i):
    return (i << 1) & 3


@annotate(i='int', return_='double')
def _declaring_kernel(i):
    total = declare('double')  # noqa: F821 - compyle's own code-generation builtin
    total = 0.0
    total += i
    return total


@annotate(i='int', return_='int')
def _flag_kernel(i):
    keep = True
    out = 0
    if keep:
        out = i
    return out


class TestRestoredAstAliases:
    """What CPython used to provide, and nothing wider."""

    def test_ast_str_matches_only_string_constants(self):
        with restored_ast_aliases():
            assert isinstance(ast.Constant(value="depth"), ast.Str)
            # A looser shim matching any Constant would make compyle accept
            # declare(3) and fail further in, with a worse message than now.
            assert not isinstance(ast.Constant(value=1.5), ast.Str)
            assert not isinstance(ast.Constant(value=3), ast.Str)
            assert not isinstance(ast.Constant(value=None), ast.Str)

    def test_ast_str_rejects_non_constant_nodes(self):
        with restored_ast_aliases():
            assert not isinstance(ast.Name(id="x"), ast.Str)

    def test_value_aliases_read_through(self):
        with restored_ast_aliases():
            assert ast.Constant(value="matrix").s == "matrix"
            assert ast.Constant(value=2.5).n == 2.5

    def test_every_restored_name_is_declared(self):
        """RESTORED_AST_NAMES is what the GPU probe subtracts; it must be true."""
        with restored_ast_aliases():
            for name in RESTORED_AST_NAMES:
                assert hasattr(ast, name), f"RESTORED_AST_NAMES claims {name}"

    def test_patches_do_not_outlive_the_block(self):
        with restored_ast_aliases():
            pass
        assert not hasattr(ast, "Str")
        assert "s" not in vars(ast.Constant)
        assert "n" not in vars(ast.Constant)

    def test_patches_are_undone_after_an_exception(self):
        with pytest.raises(RuntimeError):
            with restored_ast_aliases():
                raise RuntimeError("boom")
        assert not hasattr(ast, "Str")

    def test_a_future_real_ast_str_is_preserved(self):
        """If Python ever brings it back, the shim must not clobber it."""
        sentinel = object()
        ast.Str = sentinel
        try:
            with restored_ast_aliases():
                assert ast.Str is not sentinel
            assert ast.Str is sentinel
        finally:
            del ast.Str


@requires_compyle
class TestRestoredConstantVisitors:
    """The silent half: literals must not translate to the word None."""

    def test_visitors_are_installed_and_removed(self):
        classes = (compyle_translator.CConverter, compyle_jit.AnnotationHelper)
        with restored_constant_visitors():
            for cls in classes:
                assert "visit_Constant" in vars(cls)
        for cls in classes:
            assert "visit_Constant" not in vars(cls)

    def test_there_are_no_unrepairable_gaps_in_this_installation(self):
        """
        A class with neither visit_Constant nor any legacy visitor cannot be
        repaired by dispatching, and must be reported rather than patched
        hopefully — the GPU probe refuses on a non-empty list.
        """
        assert visitor_repair_gaps() == []

    def test_numeric_literals_survive_translation(self):
        """
        The decisive test: real compyle, translating real source.

        Without the repair the output is `((i << None) & None)` — this is the
        exact shape of the line that broke the Z-order NNPS kernel.
        """
        with compyle_python314_compat():
            code = compyle_translator.CConverter().parse_function(_shift_kernel)
        assert "None" not in code
        assert "<< 1" in code and "& 3" in code

    def test_a_declare_call_reads_its_string_argument(self):
        """
        `declare("matrix(3)")` is the loud site: compyle asks
        isinstance(node, ast.Str) and then reads node.s.
        """

        with compyle_python314_compat():
            code = compyle_translator.CConverter().parse_function(_declaring_kernel)
        assert "double total;" in code
        assert "None" not in code

    def test_booleans_are_not_translated_as_numbers(self):
        """
        True/False/None were NameConstant, never Num, and bool subclasses int —
        so the dispatch order is load-bearing, not cosmetic.
        """

        with compyle_python314_compat():
            code = compyle_translator.CConverter().parse_function(_flag_kernel)
        assert "None" not in code
        assert "keep = 1" in code

    def test_an_already_fixed_compyle_would_be_left_alone(self):
        """A compyle with its own visit_Constant must not be overridden."""
        own = object()
        compyle_translator.CConverter.visit_Constant = own
        try:
            with restored_constant_visitors():
                assert compyle_translator.CConverter.visit_Constant is own
            assert compyle_translator.CConverter.visit_Constant is own
        finally:
            del compyle_translator.CConverter.visit_Constant


class TestConditionalCompat:
    """The CPU path generates Cython by another route and needs no patching."""

    def test_disabled_installs_nothing(self):
        with compyle_python314_compat_if(False):
            assert not hasattr(ast, "Str")

    def test_enabled_installs_the_patches(self):
        with compyle_python314_compat_if(True):
            assert hasattr(ast, "Str")
        assert not hasattr(ast, "Str")
