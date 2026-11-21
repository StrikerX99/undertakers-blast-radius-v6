"""Verify bounded optimizer edits at the input to the unchanged relational planner."""

import ast
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import pickle
import tempfile

import forkprobe
from checkpoint_graph import expression_digest
from query_case import CASE, source_environment
from query_impact import comparison_edit
from source_fast import local_function
from workers import schedule


@lru_cache(maxsize=1)
def reference():
    return json.loads(
        Path(__file__).with_name("optimizer-checkpoints.json").read_bytes()
    )


def metadata_projection_edit(old, new, equal):
    """Recognize a change to the order of a comprehension stored as node metadata."""
    changes = 0

    def visit(a, b):
        nonlocal changes
        if equal(a, b):
            return True
        if type(a) is not type(b):
            return False
        if (
            isinstance(a, ast.Assign)
            and len(a.targets) == 1
            and equal(a.targets, b.targets)
        ):
            target = a.targets[0]
            x, y = a.value, b.value
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "meta"
                and isinstance(target.slice, ast.Constant)
                and type(target.slice.value) is str
                and isinstance(x, ast.ListComp)
                and isinstance(y, ast.ListComp)
                and len(x.generators) == len(y.generators) == 1
                and equal(x.elt, y.elt)
                and isinstance(x.elt, (ast.Name, ast.Attribute))
            ):
                u, v = x.generators[0], y.generators[0]

                def strip(expr):
                    return (
                        expr.args[0]
                        if isinstance(expr, ast.Call)
                        and isinstance(expr.func, ast.Name)
                        and expr.func.id == "reversed"
                        and len(expr.args) == 1
                        and not expr.keywords
                        else expr
                    )

                if (
                    not u.is_async
                    and not v.is_async
                    and not u.ifs
                    and not v.ifs
                    and equal(u.target, v.target)
                    and not equal(u.iter, v.iter)
                    and equal(strip(u.iter), strip(v.iter))
                ):
                    changes += 1
                    return True
        if isinstance(a, ast.AST):
            return all(visit(getattr(a, k), getattr(b, k)) for k in a._fields)
        if isinstance(a, list) and len(a) == len(b):
            return all(visit(x, y) for x, y in zip(a, b))
        return False

    return visit(old, new) and changes == 1


def candidate_queries(selector, changes, selected, apply, equal):
    case = selector.by_name.get(CASE)
    if case not in selected or len(changes) != 1:
        return
    change = changes[0]
    path = change["old"]
    if (
        path != change["new"]
        or not path.startswith("sqlglot/optimizer/")
        or not path.endswith(".py")
    ):
        return
    saved = (
        schedule([selector.by_number[i] for i in selected])[1]
        - schedule([selector.by_number[i] for i in selected if i != case])[1]
    ) / 1000
    if saved < 8:
        return
    source, tree = selector.source(path)
    updated, old_lines, new_lines = apply(source, change)
    funcs = local_function(
        tree, source.splitlines(True), updated.splitlines(True), old_lines | new_lines
    )
    if funcs is None:
        return
    a, b = funcs
    if not isinstance(a, ast.FunctionDef) or a.decorator_list or a.name != b.name:
        return
    if not metadata_projection_edit(a, b, equal):
        try:
            edits = comparison_edit(a, b, equal)
        except (TypeError, ValueError, RecursionError):
            return
        if len(edits) != 1:
            return
        node, operation, replacements = edits[0]
        before = type(node.ops[0]).__name__
        identity = {"Is", "IsNot"}
        ordinary = {"Eq", "NotEq", "Lt", "LtE", "Gt", "GtE"}
        if before in identity:
            if operation not in identity or any(x is not None for x in replacements):
                return
        elif before not in ordinary or operation not in ordinary:
            return
        elif not any(
            isinstance(expr, ast.Constant) and type(expr.value) is int
            for expr in (node.left, node.comparators[0])
        ):
            return
        elif any(
            replacement is not None and replacement[0] != "int"
            for replacement in replacements
        ):
            return
    data = reference()
    if (
        selector.mapping["commit"] != data["commit"]
        or data["sources"].get(path) != hashlib.sha256(source.encode()).hexdigest()
    ):
        return
    keys = data["sites"].get(path, {}).get(f"{a.lineno}:{a.name}")
    if not keys:
        # The function may also run during setup, reference SQL construction,
        # row evaluation, or outside an observed optimizer invocation.
        return
    return case, keys, min(7.5, saved * 0.55)


def check(payload, env):
    import signal
    import sys

    root, indices, seconds, marker = payload
    os.environ.update(env)
    os.chdir(root)
    sys.path.insert(0, str(root))
    signal.signal(signal.SIGPROF, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_PROF, seconds)

    from sqlglot import parse_one
    import sqlglot.executor as executor
    from tests.helpers import load_sql_fixture_pairs

    data = reference()
    query_data = json.loads(
        Path(__file__).with_name("executor-queries.json").read_bytes()
    )
    if query_data["commit"] != data["commit"] or set(query_data["queries"]) != set(
        data["graphs"]
    ):
        return
    scope = source_environment(root, query_data["driver_sha"])
    original = executor.optimize
    queries = list(load_sql_fixture_pairs("optimizer/tpc-ds/tpc-ds.sql"))

    class Matched(Exception):
        pass

    def compare(*args, **kwargs):
        graph = original(*args, **kwargs)
        if expression_digest(graph) != expected:
            raise ValueError("Optimizer output changed")
        raise Matched

    executor.optimize = compare
    for i in indices:
        meta, sql, _ = queries[i]
        if (
            hashlib.sha256(sql.encode()).hexdigest()
            != query_data["queries"][str(i)]["sql"]
        ):
            return
        expected = data["graphs"][str(i)]
        expr = pickle.loads(pickle.dumps(parse_one(sql)))
        try:
            scope["mp_execute"](expr, meta)
        except Matched:
            continue
        return
    marker.touch()


def verify(selector, changes, selected, apply, equal, checkout, remaining):
    if remaining < 4:
        return selected
    request = candidate_queries(selector, changes, selected, apply, equal)
    if request is None:
        return selected
    number, indices, cpu_limit = request
    with tempfile.TemporaryDirectory(prefix="br-plan-") as tmp:
        root = Path(tmp) / "repo"
        marker = Path(tmp) / "verified"
        checkout(root, changes, selector)
        env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")

        def worker(payload):
            check(payload, env)

        ok = forkprobe.run(
            (root, indices, cpu_limit, marker),
            env,
            worker,
            min(remaining, cpu_limit + 2),
        )
        if ok and marker.is_file():
            return selected - {number}
    return selected
