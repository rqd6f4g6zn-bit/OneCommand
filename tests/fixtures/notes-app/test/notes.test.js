const test = require("node:test");
const assert = require("node:assert");
const { validateTitle } = require("../dist/notes.js");

test("trims and accepts a title", () => assert.strictEqual(validateTitle("  Milk "), "Milk"));
test("rejects empty and non-string titles", () => {
  assert.strictEqual(validateTitle("   "), null);
  assert.strictEqual(validateTitle(42), null);
});
