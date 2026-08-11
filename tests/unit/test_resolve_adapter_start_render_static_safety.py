"""Static AST proof of the new `start_render` pathway's mutation surface.

`src/redline_core/resolve/adapter.py` is a large, shared file: it already
contains genuine, reviewed calls to `AddRenderJob`, `DeleteRenderJob`,
`SetRenderSettings`, `LoadRenderPreset`, `LoadProject`, and
`SetCurrentTimeline` elsewhere (inside `queue_render_job()`/`import_media()`/
`build_timeline()`/`place_clips()`), and to `StopRendering`/`DeleteRenderJob`
elsewhere (inside `cancel_render()`'s helpers). A whole-file scan for those
names would therefore always "fail" -- the correct, precise claim this
module proves is narrower: that the *new* `start_render()` method and every
private helper it introduces do not reach any of those names, and that
`StartRendering` itself is called at exactly one place in the entire file.

Rev2 correction: the mutation surface now spans more than `start_render()`
and one postcondition helper. `start_render()` itself only runs the
pre-mutation guards (current-project identity, queued-job/timeline
identity, status, `IsRenderingInProgress()`); the actual `StartRendering()`
call and its outcome reconciliation live in
`_invoke_start_rendering_and_reconcile()`/`_poll_for_rendering()`.

Rev3 correction: two more pre-mutation guards join the pathway --
`_strict_alias_value()` (start-owned, alias-conflict-and-malformation-aware
identity resolution, deliberately separate from the legacy
`_render_job_id_from_job()` other pathways still use unchanged) and
`_require_exact_queued_output_destination()` (binds the queued job's own
`TargetDir`/`OutputFilename` against the persisted expected output path).
All seven methods are scoped together here as "the start pathway".
"""
from __future__ import annotations

import ast
from pathlib import Path

import redline_core.resolve.adapter as adapter_module

_ADAPTER_PATH = Path(adapter_module.__file__)

_PROHIBITED_DURING_START = frozenset(
    {
        "AddRenderJob",
        "DeleteRenderJob",
        "DeleteAllRenderJobs",
        "StopRendering",
        "SetRenderSettings",
        "LoadRenderPreset",
        "LoadProject",
        "SetCurrentTimeline",
    }
)

# Every method that participates in the start_render() pathway: the
# pre-mutation identity/status/rendering-state guards (Rev3: including the
# strict, start-owned alias resolver and the queued-output-destination
# check), the method that actually invokes StartRendering() and reconciles
# its outcome, and the getter-only postcondition poll it uses.
_START_RENDER_FUNCTION_NAMES = frozenset(
    {
        "start_render",
        "_require_exact_current_project",
        "_strict_alias_value",
        "_require_exact_queued_job_identity",
        "_require_exact_queued_output_destination",
        "_invoke_start_rendering_and_reconcile",
        "_poll_for_rendering",
    }
)

_START_RENDERING_CALL_SITE_FUNCTION_NAME = "_invoke_start_rendering_and_reconcile"


def _adapter_ast() -> ast.Module:
    # utf-8-sig: adapter.py is (pre-existingly, unrelated to this change)
    # saved with a UTF-8 byte-order mark; Python's import machinery already
    # tolerates this transparently, but ast.parse() on manually-read text
    # needs the BOM stripped first or it raises SyntaxError on the first
    # character.
    source = _ADAPTER_PATH.read_text(encoding="utf-8-sig")
    return ast.parse(source, filename=str(_ADAPTER_PATH))


def _resolve_script_adapter_class(tree: ast.Module) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ResolveScriptAdapter":
            return node
    raise AssertionError("could not find class ResolveScriptAdapter in adapter.py")


def _find_functions(tree: ast.Module, names: frozenset[str]) -> list[ast.FunctionDef]:
    """Finds function definitions by name, scoped to `ResolveScriptAdapter`
    only -- `ResolveAdapter`'s own abstract method of the same name (an
    `@abstractmethod` stub with no real body) must not be conflated with
    the real implementation this module actually proves properties about.
    """
    scope = _resolve_script_adapter_class(tree)
    found = []
    for node in ast.walk(scope):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found.append(node)
    return found


def _attribute_names_in(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def test_start_render_function_exists_exactly_once():
    tree = _adapter_ast()
    matches = _find_functions(tree, frozenset({"start_render"}))
    assert len(matches) == 1


def test_all_start_render_pathway_helpers_exist_exactly_once():
    tree = _adapter_ast()
    for name in _START_RENDER_FUNCTION_NAMES:
        matches = _find_functions(tree, frozenset({name}))
        assert len(matches) == 1, f"expected exactly one definition of {name}, found {len(matches)}"


def test_start_render_pathway_never_calls_prohibited_mutation_methods():
    tree = _adapter_ast()
    functions = _find_functions(tree, _START_RENDER_FUNCTION_NAMES)
    assert functions, "expected to find every start_render pathway function"

    for function in functions:
        names = _attribute_names_in(function)
        overlap = names & _PROHIBITED_DURING_START
        assert overlap == set(), f"{function.name} reaches prohibited method(s): {overlap}"


def test_start_render_pathway_never_calls_load_project():
    """Explicit, narrowly-named regression for the Rev2 mission requirement
    'Do NOT call LoadProject()' during the current-project identity check --
    kept as its own test, not merely folded into the general prohibited-set
    scan above, because this specific guarantee was independently called
    out as its own finding."""
    tree = _adapter_ast()
    functions = _find_functions(tree, _START_RENDER_FUNCTION_NAMES)
    for function in functions:
        assert "LoadProject" not in _attribute_names_in(function)


def test_start_render_pathway_never_calls_set_current_timeline():
    """Explicit, narrowly-named regression for the Rev2 mission requirement
    'Do NOT call SetCurrentTimeline()' during the queued-job/timeline
    identity check."""
    tree = _adapter_ast()
    functions = _find_functions(tree, _START_RENDER_FUNCTION_NAMES)
    for function in functions:
        assert "SetCurrentTimeline" not in _attribute_names_in(function)


def test_start_rendering_is_called_from_exactly_one_site_in_the_whole_file():
    tree = _adapter_ast()
    all_attribute_names = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    occurrences = [name for name in all_attribute_names if name == "StartRendering"]
    assert len(occurrences) == 1


def test_start_rendering_call_site_is_inside_its_reconciliation_helper():
    """Rev2: the StartRendering() call site moved out of start_render()
    itself and into _invoke_start_rendering_and_reconcile(), which
    start_render() calls only after every pre-mutation guard has passed."""
    tree = _adapter_ast()
    (function,) = _find_functions(tree, frozenset({_START_RENDERING_CALL_SITE_FUNCTION_NAME}))
    names_in_function = _attribute_names_in(function)
    assert "StartRendering" in names_in_function


def test_start_render_itself_never_calls_start_rendering_directly():
    """start_render() must delegate the actual mutation call to
    _invoke_start_rendering_and_reconcile() rather than calling
    StartRendering() inline -- keeping every pre-mutation guard textually
    separated from the one place the mutation itself can happen."""
    tree = _adapter_ast()
    (start_render_function,) = _find_functions(tree, frozenset({"start_render"}))
    assert "StartRendering" not in _attribute_names_in(start_render_function)


def test_start_render_pathway_never_loops_around_start_rendering():
    """Structurally proves no loop node (for/while) in any start_render
    pathway function contains the StartRendering() call -- i.e. it is not
    reachable through any retry construct, not merely "only called once in
    this particular test run"."""
    tree = _adapter_ast()
    functions = _find_functions(tree, _START_RENDER_FUNCTION_NAMES)

    for function in functions:
        for node in ast.walk(function):
            if isinstance(node, (ast.For, ast.While)):
                names_in_loop = _attribute_names_in(node)
                assert "StartRendering" not in names_in_loop


def test_strict_alias_value_is_pure_dict_logic():
    """_strict_alias_value() must never touch the Resolve API at all --
    it operates purely on the plain dict/tuple arguments it's given, which
    structurally guarantees it can't be a hidden second mutation path."""
    tree = _adapter_ast()
    (helper,) = _find_functions(tree, frozenset({"_strict_alias_value"}))
    names = _attribute_names_in(helper)
    assert names <= {"strip", "append"}


def test_require_exact_queued_output_destination_never_touches_resolve_api():
    """_require_exact_queued_output_destination() takes the already-fetched
    queue entry dict, not a live Resolve `project` object -- structurally
    proving it can only do path/string comparison, plus delegating to the
    getter-only _strict_alias_value(), never a fresh Resolve API call."""
    tree = _adapter_ast()
    (helper,) = _find_functions(tree, frozenset({"_require_exact_queued_output_destination"}))
    names = _attribute_names_in(helper)
    assert names <= {"_strict_alias_value", "expanduser", "resolve", "parent", "name"}


def test_poll_for_rendering_postcondition_helper_is_getter_only():
    """The postcondition helper may only call GetRenderJobStatus (a getter)
    -- proving the bounded wait never re-invokes any mutation method,
    including StartRendering itself, while polling."""
    tree = _adapter_ast()
    (helper,) = _find_functions(tree, frozenset({"_poll_for_rendering"}))
    names = _attribute_names_in(helper)
    assert names <= {"GetRenderJobStatus", "get", "strip", "casefold", "sleep"}
    assert "StartRendering" not in names


def test_start_render_prohibited_terms_absent_as_string_literals_too():
    """Defense in depth: none of the prohibited method names should appear
    as a bare string literal within any start_render pathway function's own
    subtree either (e.g. smuggled into a dynamic getattr() call) -- the
    pathway only ever dispatches through ordinary attribute access or
    getattr() lookups of getter names (e.g. `GetName`), never through
    string-keyed dynamic dispatch of a mutation method."""
    tree = _adapter_ast()
    functions = _find_functions(tree, _START_RENDER_FUNCTION_NAMES)
    for function in functions:
        string_literals = {
            n.value
            for n in ast.walk(function)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        overlap = string_literals & _PROHIBITED_DURING_START
        assert overlap == set(), f"{function.name} contains prohibited method name(s) as string literals: {overlap}"


def test_mock_resolve_adapter_start_render_never_calls_real_resolve_api():
    """MockResolveAdapter.start_render() must remain pure in-memory
    bookkeeping -- no DaVinciResolveScript import, no Resolve object
    anywhere in its module."""
    import redline_core.resolve.mock as mock_module

    source = Path(mock_module.__file__).read_text(encoding="utf-8")
    assert "DaVinciResolveScript" not in source
    assert "StartRendering" not in source
