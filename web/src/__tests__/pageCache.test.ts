import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";
import { invalidatePageReview } from "../api/pageCache";

it.each([undefined, 2])("invalidates dependent page evidence across series scopes (%s)", pageNumber => {
  const client = new QueryClient();
  const keys = ["book", "book~part_0001", "book~part_0002"].flatMap(scope => [
    ["project", scope, "complete-pages"],
    ["project", scope, "complete-pages", 2],
    ["project", scope, "page-visual-review", 2],
    ["project", scope, "page-analysis-estimate", 2],
    ["project", scope, "page-render-correction", 2, 3],
    ["project", scope, "status"],
    ["project", scope, "generation-jobs", []],
  ]);
  keys.push(["credits", "history"]);
  for (const key of keys) client.setQueryData(key, {});
  client.setQueryData(["project", "other", "complete-pages"], {});
  invalidatePageReview(client, "book~part_0001", pageNumber);
  for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  expect(client.getQueryState(["project", "other", "complete-pages"])?.isInvalidated).toBe(false);
  client.clear();
});
