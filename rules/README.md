# Canary diagnostic policy

The project keeps compiler errors and demonstrated security failures blocking.
Syntax-only audit checks and maintainability heuristics do not establish a bug
on their own.

## Python exception handling

`ast-grep-rules/rules/unchecked-throwing-call-python.yml` overrides the bundled
rule with the same identifier. It preserves the match patterns but reports them
as warnings. Canary's host controller propagates failures to its worker, socket,
and SSH boundaries. Adding a catch around every parsing or file operation would
hide those failures rather than improve recovery.

Run the fixtures with an installed ast-grep CLI:

```sh
ast-grep test -c rules/ast-grep-rules/sgconfig.yml --skip-snapshot-tests
```

The fixtures retain detection of unguarded calls, including calls handled by
another function, and exclude locally guarded calls. The caller-handled case
remains an audit warning because the matcher does not trace callers.

## Frontend imports

`../web/.pi-lens.json` disables only `find-import-file-without-extension` in the
web package. `../web/tsconfig.app.json` and `../web/tsconfig.node.json` use bundler
resolution, so extensionless relative imports are supported. Other packages and
all other diagnostic rules remain unaffected. TypeScript and the Vite build
still check that frontend imports resolve.

## Narrow false positives

Use pi-lens's content-bound `false-positive` disposition for reviewed individual
findings, such as the fixed host-loopback health request or an exception
classifier that intentionally accepts `unknown`. These are local diagnostic
store entries, not shared source suppressions. Editing the flagged line makes
pi-lens reconsider the finding. Do not disable a security rule across a file or
project to silence a single reviewed case.

Complexity and fan-out warnings remain visible. The diagnostic policy does not
raise their thresholds or treat a passing test suite as proof of maintainability.
