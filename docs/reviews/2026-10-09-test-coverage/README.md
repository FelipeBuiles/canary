# LCOV and Cobertura coverage snapshot

**Historical — October 9, 2026.** Standard coverage exports from the measured
runs in the [coverage analysis](../2026-10-09-test-coverage.md), against source
commit `2215da0a925f91cce069b30b40805863cad32b3e`.

| Scope | LCOV | Cobertura XML |
| --- | --- | --- |
| Application Python and gateway handlers | [python.lcov](python.lcov) | [python.cobertura.xml](python.cobertura.xml) |
| Frontend TypeScript/TSX | [frontend.lcov](frontend.lcov) | [frontend.cobertura.xml](frontend.cobertura.xml) |

Load either format into a compatible coverage viewer with the repository root
as its source root. LCOV `SF` records and Cobertura class filenames are relative
to the repository; XML `<source>` is `.`. There are no machine-specific source
paths in these exports. Keep the two language reports separate when comparing
percentages: their instrumentation and branch definitions differ.

Python combines the backend and gateway runs, excludes handler test modules,
and includes unexecuted application/handler modules. Its totals are 32,511 /
37,307 executable lines and 9,164 / 12,008 branch outcomes across 235 files.
Frontend includes unexecuted matching source modules, excludes tests and type
declarations, and covers 7,474 / 9,401 executable lines and 9,442 / 12,681 branch
outcomes across 279 files. Every exported source path and both formats' covered
and total counts were checked against the
[per-file measurements](../2026-10-09-test-coverage-metrics.json).

Python's trace records whether a line or branch executed, so its LCOV hit values
are presence indicators rather than execution frequencies. The analysis lists
skipped tests and measurement limits; these files do not imply live provider,
database, deployment, or image-quality verification.

## Regenerating standard reports

First capture the runs described in the analysis with the matching coverage
tools available. From the repository root, export combined Python trace data:

```sh
COVERAGE_FILE=/tmp/canary-combined.coverage novel_to_comic/.venv/bin/python \
  -m coverage lcov \
  --include='novel_to_comic/src/novel_to_comic/*,litellm_handlers/*' \
  --omit='litellm_handlers/test_*.py' -o /tmp/canary-python.lcov
COVERAGE_FILE=/tmp/canary-combined.coverage novel_to_comic/.venv/bin/python \
  -m coverage xml \
  --include='novel_to_comic/src/novel_to_comic/*,litellm_handlers/*' \
  --omit='litellm_handlers/test_*.py' -o /tmp/canary-python.cobertura.xml
```

For frontend, add `--coverage.reporter=lcovonly` and
`--coverage.reporter=cobertura` to the documented Vitest coverage command.
These emit `lcov.info` and `cobertura-coverage.xml` in its reports directory.
Vitest's default source root is `web/`; the checked-in snapshot was exported
from the captured `coverage-final.json` using Vitest's Istanbul coverage/report
libraries with the repository root as `projectRoot`. Python's native exporters
produced its reports. XML source roots were then normalized to `.` while keeping
repository-relative filenames and all coverage records intact.

New runs should produce a new dated snapshot or CI artifacts, rather than
silently overwrite this historical evidence. Coverage collection dependencies
and ongoing CI reporting are not added by this snapshot.
