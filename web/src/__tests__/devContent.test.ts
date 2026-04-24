import { describe, it, expect } from "vitest";
import {
  redactDevText,
  redactDevParameters,
} from "../lib/devContent";

describe("redactDevText", () => {
  it("redacts windows paths", () => {
    const result = redactDevText(
      "C:\\Users\\Alice\\novel.txt is the input"
    );
    expect(result).toBe("[path hidden] is the input");
  });

  it("redacts posix paths", () => {
    const result = redactDevText("/home/alice/novel.txt");
    expect(result).toBe("[path hidden]");
  });

  it("redacts long hashes", () => {
    const result = redactDevText(
      "commit abcdef1234567890abcdef1234567890abcdef is here"
    );
    expect(result).toBe("commit [hash hidden] is here");
  });

  it("redacts model names", () => {
    const result = redactDevText(
      "Using gemini-3-pro-image-preview for generation"
    );
    expect(result).toBe("Using [model hidden] for generation");
  });

  it("redacts flux model names", () => {
    const result = redactDevText(
      "Model: black-forest-labs/flux-1-dev"
    );
    expect(result).toBe("Model: [model hidden]");
  });

  it("redacts multiple occurrences", () => {
    const result = redactDevText(
      "/path/a.txt and /path/b.txt are both paths"
    );
    expect(result).toBe("[path hidden] and [path hidden] are both paths");
  });

  it("returns unchanged string if no matches", () => {
    const result = redactDevText("hello world normal text");
    expect(result).toBe("hello world normal text");
  });
});

describe("redactDevParameters", () => {
  it("returns string unchanged through redactDevText", () => {
    const result = redactDevParameters("hello /home/alice/test.txt world");
    expect(result).toBe("hello [path hidden] world");
  });

  it("recursively processes arrays", () => {
    const result = redactDevParameters([
      "/home/alice/file.txt",
      "normal text",
    ]);
    expect(result).toEqual(["[path hidden]", "normal text"]);
  });

  it("recursively processes nested objects", () => {
    const result = redactDevParameters({
      name: "Alice",
      path: "/home/alice/novel.txt",
      nested: { ref: "/home/alice/ref.json" },
    });
    // Keys matching DEV_KEY_RE (path, ref, etc.) → "[hidden]" regardless of content
    expect(result).toEqual({
      name: "Alice",
      path: "[hidden]",
      nested: { ref: "[hidden]" },
    });
  });

  it("hides values of keys matching DEV_KEY_RE", () => {
    const result = redactDevParameters({
      model: "gemini-3-pro-image-preview",
      temperature: 0.7,
      path: "/home/bob/file.txt",
    });
    // model and path match DEV_KEY_RE → [hidden]
    // temperature does not match
    expect(result).toEqual({
      model: "[hidden]",
      temperature: 0.7,
      path: "[hidden]",
    });
  });

  it("returns non-string/non-object values unchanged", () => {
    expect(redactDevParameters(42)).toBe(42);
    expect(redactDevParameters(true)).toBe(true);
    expect(redactDevParameters(null)).toBe(null);
  });

  it("handles empty object", () => {
    expect(redactDevParameters({})).toEqual({});
  });

  it("handles empty array", () => {
    expect(redactDevParameters([])).toEqual([]);
  });
});
