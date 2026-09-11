# Domain documentation

Use [the glossary](../../CONTEXT.md) for unfamiliar domain concepts and
[ADRs](../adr/) for decisions relevant to the boundary being changed. Read the
needed entries once; there is no prerequisite to read the entire glossary or
ADR collection before exploring code.

Use established vocabulary in output. Correct clearly stale wording against
current evidence; flag substantive architectural conflicts rather than silently
changing an accepted decision. Ask only when the ambiguity affects correctness
or scope. Missing terminology alone does not block unrelated work.

Python source lives in `novel_to_comic/src/novel_to_comic/`; frontend source lives
in `web/src/`. [Agent context](../reference/agent-context.md#code-navigation)
provides focused code navigation.
