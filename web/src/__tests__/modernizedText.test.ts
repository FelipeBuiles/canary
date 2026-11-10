import { describe, expect, it } from "vitest";
import { modernizedFilename, modernizedText } from "../lib/modernizedText";

describe("modernized text export", () => {
  it("joins paragraphs with blank lines so a new production splits them the same way", () => {
    expect(modernizedText(["Part I", " “Listen to the wind,” Mr. White said. "])).toBe(
      "Part I\n\n“Listen to the wind,” Mr. White said.\n",
    );
  });

  it("names the file after the project and model", () => {
    expect(modernizedFilename("The Monkey’s Paw", "gemini-4-carbon")).toBe("the-monkeys-paw-gemini-4-carbon.txt");
    expect(modernizedFilename("", "")).toBe("modernized.txt");
  });
});
