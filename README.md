# Blast Radius selector

The entry selects tests for independent patches against SQLGlot at
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Build with the Dockerfile at
this directory's root. At runtime, it reads mounted patches and `tests.json`
from `/data`, and writes the requested JSON lines to stdout.

If a hunk's reported position disagrees with the source, the selector can
relocate the hunk when every old line matches at one location. Ambiguous
context triggers a conservative fallback. The selector applies every change
in a patch before running a verification probe. It maps edits to baseline
coverage, fixture and source-file reads, dictionary value reads, and recorded
operands of comparisons. For a supported comparison change, it evaluates
the new comparison against the recorded operands. Missing information can
broaden the selection. Small candidate groups can run against the patched
checkout. Only completed, passing tests may be removed. On Linux, a probe can fork a Python process that has loaded the standard library. The child then imports SQLGlot and its tests from the patched checkout.

The scheduler tries one through eight workers, scores each partition in
integer milliseconds, and emits the cheapest one it found. Empty selections
use no workers. The Docker build downloads the pinned SQLGlot archive and
precompiles its Python code. It also partitions the plain coverage map by source file, so each run loads only the portions it needs. Hash-based bytecode validation makes Python
recompile changed source in the temporary checkout.

## How the selector uses the baseline

Short-circuit operands, conditional branches and comprehension elements have their own test coverage. Changes can be narrowed to the tests that evaluated an expression. For changes to scalar class settings, the map distinguishes reads of the value from uses in comparisons or boolean conditions. Derived date formatting maps have dependencies across SQLGlot dialects, including inverse lookups. Source-reading tests retain their own dependencies even when a module compiles identically.

On eligible changes to nested expression builders, a child process replays observed primitive inputs and compares the complete supported expression graph. For fixture-only and method-local changes, the selector can compare the records produced by the pinned fixture loaders and run inexpensive candidate methods in the complete patched checkout. The isolated method environment includes the MIT-licensed mypy_extensions package used by the reference suite.

The TPC-DS executor test submits independent SQL queries and compares the Python result with DuckDB. The baseline collector runs the passing test, observes comparison operands per query, and fingerprints each returned table and generated DuckDB statement. For a supported optimizer comparison edit, the selector runs affected queries with the pinned fixture tables through the patched execution code. It requires exact equality of ordered results, column names and the SQL submitted to DuckDB. Unobserved operand values retain their queries. Edits to the corpus, changes outside the supported comparison, excessive replay cost or an incomplete result keep the original test schedule. The map records passing baseline executions; runtime decisions use the supplied patch.

## Regenerating the maps

The committed maps were generated from the unmodified pinned checkout. The
Docker build uses them as plain JSON files. To regenerate them offline,
use a Linux development machine with Python 3.13. Allow time for the full
instrumented suite, including the large parser stress test.

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-build.txt
.venv/bin/python fetch_baseline.py ../sqlglot-baseline
SQLGLOT_ROOT="$PWD/../sqlglot-baseline" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python build_map.py coverage-map.raw.json
.venv/bin/python tools/source_reads.py ../sqlglot-baseline coverage-map.raw.json "$PWD/source-reads.json"
.venv/bin/python tools/import_lines.py ../sqlglot-baseline coverage-map.raw.json "$PWD/import-lines.json"
.venv/bin/python tools/finalize_map.py coverage-map.raw.json ../sqlglot-baseline source-reads.json import-lines.json coverage-map.json
.venv/bin/python tools/build_config_coverage.py ../sqlglot-baseline coverage-map.json config-reads.json
PYTHONPATH="$PWD" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python tools/build_dispatch_coverage.py ../sqlglot-baseline coverage-map.json dispatch.json
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python tools/profile_external.py ../sqlglot-baseline dispatch.json dispatch.json
```

The following commands regenerate the additional baseline observations. Run them from the submission directory after completing the commands above. Keep the virtual environment first on PATH so tests that spawn Python use the pinned dependencies.

```bash
export PATH="$PWD/.venv/bin:$PATH"
export PYTHONPATH="$PWD"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 SKIP_INTEGRATION=0
python tools/build_relations.py ../sqlglot-baseline coverage-map.json set-relations.json
python tools/build_gates.py ../sqlglot-baseline coverage-map.json gates.json
python tools/build_fixture_views.py ../sqlglot-baseline coverage-map.json fixture-views.json
python tools/build_scalar_coverage.py ../sqlglot-baseline coverage-map.json scalars.json
python tools/build_time_dependencies.py ../sqlglot-baseline coverage-map.json time-dependencies.raw.json
python tools/profile_time_readers.py ../sqlglot-baseline time-dependencies.raw.json time-dependencies.json
python tools/build_replay.py ../sqlglot-baseline coverage-map.json replay.json
python tools/build_queries.py ../sqlglot-baseline executor-queries.json coverage-map.json
python tools/reference_imports.py reference-imports.json
```

The build generates the bytecode fingerprint index with the same interpreter, compiler flags and source paths used at runtime. The local verification kit contains practice inputs, measured failure lists and scoring tools.

## Version 5

The selector records the actual operand at high-cardinality literal-equality comparisons on the unmodified baseline. It also records conservative per-test operand ranges at high-cardinality integer comparisons. For a supported literal or integer-threshold edit it retains tests whose values could change the result, along with unknown operands and opaque readers. The collector runs the passing pytest suite, including spawned process-pool tasks.

For a single edit to a literal dictionary key in an expression argument lookup, the selector checks whether both keys returned the identical object on every observed baseline invocation. It retains opaque processes and source-text readers.

For a change to an exception handler, the selector compares the old and new catch types against the exception classes observed at that protected block. If a change could stop catching an exception or if a newly caught exception was seen anywhere, the selector retains the existing candidates. Positive evidence of an import-time change can select the entire suite. This also covers cases where the test that first raises an exception affects later tests.

For selected optimizer edits, a separate verification step replays the affected baseline TPC-DS queries through the patched Python optimizer and compares the complete supported expression graph passed to the unchanged planner. Reachability outside this boundary, a changed graph, an unsupported edit, or an incomplete replay retains the executor test. CPU is budgeted against the simulated time that could be saved. The runtime also includes the exact public pytz wheel from the reference environment so that applicable BigQuery unittest methods can be executed in their actual patched form.

For a nonempty schedule, tests with zero recorded duration can be added at zero simulated cost. The scheduler also considers other tests that read the changed files where they fit within the busiest worker's load. Only the supplied test catalog is used to calculate durations.

Run the following from the submission directory after generating the baseline coverage map and executor query map as described above. Adjust the path to the official starter catalog for your local checkout.

```bash
export PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD"
export SKIP_INTEGRATION=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHON_CPU_COUNT=1
python tools/build_arg_lookups.py ../sqlglot-baseline coverage-map.json arg-lookups.json ../blast-radius-sample/sample/tests.json
python tools/build_exceptions.py ../sqlglot-baseline coverage-map.json exceptions.json
python tools/build_literals.py ../sqlglot-baseline coverage-map.json literals.json
python tools/build_checkpoints.py ../sqlglot-baseline coverage-map.json optimizer-checkpoints.json
```

## Version 6

The parser token profile records which token was current when a parser called the pinned SQLGlot Parser._match with a literal TokenType member. A single changed member can affect the result, token advancement or comment attachment only when the current token matches the old or the new member. The selector retains both executor tests whenever its baseline observations encounter either member or an unknown implementation. Source readers and unobserved sites keep their original schedule.

The collector runs real TPC-DS and TPC-H tests, including setup, teardown, reference queries and spawned workers. It also collects every test module and runs the entire executor test class, then conservatively unions those tokens with the individual case observations. Baseline hashes are checked before tracing. Run from the submission directory with the locked reference packages installed.

```sh
python tools/build_tokens.py ../sqlglot-baseline coverage-map.json token-cases.json
```

For a small group of candidate unittest methods on a single edited production file, the selector can run those methods in the full patched checkout and keep any that fail or skip. It limits this additional path to six candidates and a combined recorded duration of 50 ms, verifies pending imports, and watches for missing reference packages.

When an edited class setting changed an observed comparison during module initialization, the selector keeps the complete supplied catalog. Module globals can carry the changed value into tests that never read the setting directly. For a separate class of single, same-type literal edits in dialect settings, baseline instrumentation records class creation, resolved reads and opaque class-namespace accesses. The selector can narrow the schedule only for observed declarations with no recorded consumers and no opaque or raw-source readers. Positive dependencies from the original map remain selected.

Reproduce the source-access and dialect-setting observations on Linux using the pinned baseline, the reference dependencies listed above and the numbered catalog from the official starter.

```bash
python tools/build_unopened_sources.py ../sqlglot-baseline coverage-map.json ../blast-radius-sample/sample/tests.json unopened-sources.json
python tools/build_dialect_reads.py ../sqlglot-baseline coverage-map.json ../blast-radius-sample/sample/tests.json dialect-reads.json
```
