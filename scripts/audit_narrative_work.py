#!/usr/bin/env python3
"""Replay saved Adapt review inputs without generation or project mutations.

Run with the backend virtualenv. Supply a frozen project copy containing
.checkpoints/adapt/responses and optionally a sanitized events.json export.
Conflicting/missing evidence is rejected rather than stitched into a candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from novel_to_comic.narrative_review import _review_contexts, _review_prompts


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def unique(items, key):
    found = {}
    for item in items:
        identity = item[key]
        if identity in found and found[identity] != item:
            raise ValueError(f"Conflicting saved evidence for {identity}; use a single candidate snapshot.")
        found[identity] = item
    return found


def audit(snapshot: Path):
    groups = defaultdict(list)
    manifest = {}
    for path in sorted((snapshot / ".checkpoints/adapt/responses").glob("*.json")):
        raw = path.read_bytes()
        manifest[str(path.relative_to(snapshot))] = hashlib.sha256(raw).hexdigest()
        saved = json.loads(raw)
        request = json.loads(saved["input"])
        if request["request"].get("feature") != "adapt.narrative_review":
            continue
        prompt = request["request"]["user_content"]
        context = json.JSONDecoder().raw_decode(prompt.split("\n", 1)[1])[0]
        identity = {k: v for k, v in context.items() if k not in {
            "units", "supporting_units", "beats", "ledger", "signals",
        }}
        groups[(request["model"], digest(identity))].append((context, prompt))
    reviews = []
    for (model, identity), rows in groups.items():
        units = unique((u for c, _ in rows for u in c["units"]), "id")
        beats = unique((b for c, _ in rows for b in c["beats"]), "id")
        entries = []
        for c, _ in rows:
            for entry in c["ledger"]:
                if "source_unit_id" in entry:
                    entries.append(entry)
                else:
                    entries.extend({**{k: v for k, v in entry.items() if k != "source_unit_ids"},
                                    "source_unit_id": u} for u in entry["source_unit_ids"])
        ledger = unique(entries, "source_unit_id")
        base = rows[0][0]
        if set(ledger) != set(units) or set(beats) != {b["id"] for b in base["global_story"]}:
            raise ValueError("Incomplete review windows; cannot measure a complete candidate.")
        context = {k: v for k, v in base.items() if k not in {
            "units", "supporting_units", "beats", "ledger", "signals", "global_story",
        }}
        context.update(units=sorted(units.values(), key=lambda u: u["id"]),
                       beats=[beats[b["id"]] for b in base["global_story"]],
                       ledger=sorted(ledger.values(), key=lambda e: e["source_unit_id"]))
        prompts = list(_review_prompts(context))
        windows = list(_review_contexts(context))
        reviews.append({
            "model": model, "group_sha256": identity, "beats": len(beats), "units": len(units),
            "before_chars": sum(len(p) for _, p in rows), "after_chars": sum(map(len, prompts)),
            "before_max_chars": max(len(p) for _, p in rows), "after_max_chars": max(map(len, prompts)),
            "before_ledger_chars": sum(len(json.dumps(c["ledger"], ensure_ascii=False, separators=(",", ":"))) for c, _ in rows),
            "after_ledger_chars": sum(len(json.dumps(c["ledger"], ensure_ascii=False, separators=(",", ":"))) for c in windows),
        })
    events = []
    path = snapshot / "events.json"
    if path.exists():
        for event in json.loads(path.read_text()):
            runtime = event.get("metadata_json", {}).get("codex_runtime") or {}
            elapsed = None
            if event["finished_at"]:
                elapsed = (datetime.fromisoformat(event["finished_at"]) - datetime.fromisoformat(event["created_at"])).total_seconds()
            active = runtime.get("execution_elapsed_seconds")
            events.append({**{k: event.get(k) for k in (
                "id", "created_at", "finished_at", "feature", "model_alias", "status", "input_tokens",
                "output_tokens", "cost_usd", "cost_source", "estimated_cost_usd", "funding", "error_type",
            )}, "event_elapsed_seconds": elapsed, "execution_seconds": active,
                "non_execution_seconds": max(0, elapsed - active) if elapsed is not None and active is not None else None,
                "request_bytes": event.get("request_summary_json", {}).get("user_content_bytes"),
                "indeterminate": runtime.get("indeterminate")})
    return {"review_contract": "narrative_v2", "checkpoint_sha256": manifest, "reviews": reviews, "events": events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.snapshot)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Measured {len(result['reviews'])} review candidates and {len(result['events'])} usage events.")
