import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { MAX_COMMAND, MAX_TOOL, approvalSummary, truncate } from "../src/talktome/static/approval.js";

const read = (relative) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");

test("A Hermes request shows the tool and the command", () => {
  // Hermes names every request "approval" and puts the facts in the details.
  const summary = approvalSummary({
    id: "a-1",
    action: "approval",
    details: { tool: "terminal", command: "rm -rf build", request_id: "q-1" },
  });
  assert.deepEqual(summary, { tool: "terminal", command: "rm -rf build" });
});

test("The action names the tool when the details do not", () => {
  const summary = approvalSummary({ action: "Write", details: { file: "example.txt" } });
  assert.deepEqual(summary, { tool: "Write", command: "example.txt" });
});

test("A request with no known fields still says something", () => {
  assert.deepEqual(approvalSummary({ action: "approval", details: {} }), {
    tool: "A tool",
    command: "",
  });
  assert.deepEqual(approvalSummary(null), { tool: "A tool", command: "" });
  const other = approvalSummary({ action: "approval", details: { choices: ["once", "deny"] } });
  assert.equal(other.command, '{"choices":["once","deny"]}');
});

test("Long text is cut short and kept on one line", () => {
  const summary = approvalSummary({
    action: "approval",
    details: { tool: "t".repeat(200), command: `echo ${"x".repeat(400)}\n\nrm -rf /` },
  });
  assert.equal(summary.tool.length, MAX_TOOL);
  assert.equal(summary.command.length, MAX_COMMAND);
  assert.ok(summary.command.endsWith("…"));
  assert.doesNotMatch(summary.command, /\n/);
  assert.equal(truncate("  a \n b  ", 10), "a b");
});

test("A value that is not text is not used as the command", () => {
  const summary = approvalSummary({ action: "approval", details: { command: ["rm", "-rf"] } });
  assert.equal(summary.command, '{"command":["rm","-rf"]}');
});

test("The card uses text, not markup", () => {
  const call = read("../src/talktome/static/call.js");
  const renderer = call.match(/function renderApproval\(approval\) \{([\s\S]*?)\n\}/);
  assert.ok(renderer, "renderApproval is missing.");
  assert.doesNotMatch(renderer[1], /innerHTML|insertAdjacentHTML/);
  assert.match(renderer[1], /approvalTool\.textContent = summary\.tool/);
  assert.match(renderer[1], /approvalCommand\.textContent = summary\.command/);
});

test("The card answers through the approval route and names the pill status", () => {
  const call = read("../src/talktome/static/call.js");
  assert.match(call, /fetch\(`\/v1\/managed\/approvals\/\$\{encodeURIComponent\(approval\.id\)\}`/);
  assert.match(call, /JSON\.stringify\(\{ allow \}\)/);
  assert.match(call, /"Needs approval"/);
  const html = read("../src/talktome/static/call.html");
  assert.match(html, /id="approval-allow"[^>]*>Allow once</);
  assert.match(html, /id="approval-deny"[^>]*>Deny</);
});

test("The approval buttons are 44 px targets, and Allow is the primary one", () => {
  const css = read("../src/talktome/static/call.css");
  assert.match(css, /\.approval-actions button \{[\s\S]*?min-width: 44px;[\s\S]*?min-height: 44px;/);
  assert.match(css, /#approval-allow \{[\s\S]*?background: var\(--primary\);/);
  assert.match(css, /#approval-deny \{[\s\S]*?border-color: var\(--input\);/);
});

test("The notch rules for the card touch only the card", () => {
  const css = read("../src/talktome/static/call.css");
  const notch = css.slice(css.indexOf("/* The approval card in the notch mode."));
  const selectors = [...notch.matchAll(/^([^\s/@}][^{]*)\{/gm)].map((match) => match[1]);
  assert.ok(selectors.length > 0);
  for (const list of selectors) {
    for (const selector of list.split(",")) {
      assert.match(
        selector.trim(),
        /^:root\[data-surface="transcript"\] (#approval|\.approval-actions)/,
        `${selector.trim()} must stay inside the approval card`,
      );
    }
  }
});

test("The main process opens the panel for a request and closes only what it opened", () => {
  const main = read("../desktop/main.cjs");
  assert.match(main, /const approval = Boolean\(callId && snapshot\.managed\?\.approvals\?\.length\);/);
  assert.match(
    main,
    /if \(approval && !callTranscriptOpen\) \{\s*callTranscriptOpen = true;\s*approvalOpenedPanel = true;/,
  );
  assert.match(
    main,
    /else if \(!approval && approvalOpenedPanel\) \{\s*callTranscriptOpen = false;/,
  );
  assert.match(main, /transcriptWidth: request\.width,/);
});
