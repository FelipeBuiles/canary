import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PageLettering } from "@lettering-engine";
import fixture from "./fixtures/lettering.json";
import { editableSignature, historyReducer, initialHistory, letteringDraftKey, readLetteringDraft, writeLetteringDraft, type LetteringDraft } from "../lib/letteringHistory";
const state = () => structuredClone(fixture.state) as PageLettering;
beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
describe("lettering history and recovery", () => {
  it("coalesces an entire pointer gesture into one reversible edit", () => {
    const original = state();
    let history = historyReducer(initialHistory(original), { type: "begin" });
    for (let x = .2;x < .3;x += .01) {
      const next = structuredClone(history.present);
      next.elements[0].placement.x = x;
      history = historyReducer(history, { type: "preview", value: next });
    }
    expect(history.past).toHaveLength(0);
    history = historyReducer(history, { type: "commit" });
    expect(history.past).toHaveLength(1);
    const moved = history.present;
    history = historyReducer(history, { type: "undo" });
    expect(history.present).toEqual(original);
    expect(historyReducer(history, { type: "redo" }).present).toEqual(moved);
  });
  it("retains undo across a server save acknowledgment", () => {
    const original = state(), changed = state();
    changed.elements[0].text_by_locale.source = "New copy.";
    let history = historyReducer(initialHistory(original), { type: "change", value: changed });
    history = historyReducer(history, { type: "acknowledge", value: { ...changed, revision: 2, content_sha256: "saved" } });
    expect(historyReducer(history, { type: "undo" }).present).toEqual(original);
    expect(editableSignature(changed)).toBe(editableSignature(history.present));
  });
  it("cancels an interrupted drag instead of silently committing it", () => {
    const original = state(), moved = state();
    moved.elements[0].placement.x = .4;
    let history = historyReducer(initialHistory(original), { type: "begin" });
    history = historyReducer(history, { type: "preview", value: moved });
    history = historyReducer(history, { type: "cancel" });
    expect(history.present).toEqual(original);
    expect(history.past).toHaveLength(0);
  });
  it("stores revision-scoped drafts and rejects broken payloads", () => {
    const key = letteringDraftKey("book", 1);
    const draft: LetteringDraft = { version: 1, baseRevision: 1, sourceSha: "source", styleSha: "style", imageSha: "art", state: state(), updatedAt: "2026-09-15T00:00:00Z" };
    expect(writeLetteringDraft(key, draft)).toBe(true);
    expect(readLetteringDraft(key)).toEqual(draft);
    localStorage.setItem(key, '{"state":null}');
    expect(readLetteringDraft(key)).toBeNull();
    localStorage.setItem(key, "broken JSON");
    expect(readLetteringDraft(key)).toBeNull();
  });
  it("reports storage failure without pretending work is saved", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new DOMException("full"); });
    expect(writeLetteringDraft("draft", {} as LetteringDraft)).toBe(false);
  });
});
