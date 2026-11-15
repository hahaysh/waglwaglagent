import test from "node:test";
import assert from "node:assert/strict";
import { pickSuggestions, recentPrompts } from "../lib/prompt-suggestions.ts";

test("new users get varied general starter prompts, deterministic for a seed", () => {
  const first = pickSuggestions([], 1);
  assert.equal(first.length, 3);
  assert.ok(first.every((entry) => !entry.recent && entry.prompt.length > 10));
  assert.deepEqual(pickSuggestions([], 1), first);
  const seen = new Set(Array.from({ length: 20 }, (_, seed) => pickSuggestions([], seed).map((entry) => entry.label).join("|")));
  assert.ok(seen.size > 5);
});

test("returning users get their own recent prompts plus one fresh idea", () => {
  const titles = ["내일 회의 안건 정리해줘", "  내일   회의 안건 정리해줘 ", "notes.txt", "ab", "파이썬 리스트 정렬 방법"];
  assert.deepEqual(recentPrompts(titles, 2), ["내일 회의 안건 정리해줘", "파이썬 리스트 정렬 방법"]);
  const picked = pickSuggestions(titles, 7);
  assert.deepEqual(picked.map((entry) => entry.recent), [true, true, false]);
  assert.equal(picked[0].prompt, "내일 회의 안건 정리해줘");
  assert.equal(new Set(picked.map((entry) => entry.id)).size, 3);
});
