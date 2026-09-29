import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { computeVisibility } = require("../desktop/lifecycle.cjs");

test("A fresh install shows onboarding", () => {
  assert.deepEqual(computeVisibility({ onboarding: true }), {
    call: false,
    main: true,
  });
});

test("After setup the main window is hidden", () => {
  assert.deepEqual(computeVisibility({}), { call: false, main: false });
});

test("Opening settings shows the main window", () => {
  assert.deepEqual(computeVisibility({ settingsOpen: true }), {
    call: false,
    main: true,
  });
});

test("Closing settings hides the main window again", () => {
  assert.deepEqual(computeVisibility({ settingsOpen: false }), {
    call: false,
    main: false,
  });
});

test("A dismissed setup window stays hidden", () => {
  assert.deepEqual(
    computeVisibility({ onboarding: true, dismissed: true }),
    { call: false, main: false },
  );
});

test("Opening settings overrides a dismissal", () => {
  assert.deepEqual(
    computeVisibility({ onboarding: true, dismissed: true, settingsOpen: true }),
    { call: false, main: true },
  );
});

test("A live call shows the call window and hides the main window", () => {
  assert.deepEqual(computeVisibility({ callLive: true }), {
    call: true,
    main: false,
  });
});

test("A ring shows the call window while settings is closed", () => {
  assert.deepEqual(
    computeVisibility({ callLive: true, onboarding: false, settingsOpen: false }),
    { call: true, main: false },
  );
});

test("A call that ends does not show the main window", () => {
  assert.deepEqual(
    computeVisibility({ callLive: false, settingsOpen: false, onboarding: false }),
    { call: false, main: false },
  );
});

test("Settings can stay open during a call", () => {
  assert.deepEqual(computeVisibility({ callLive: true, settingsOpen: true }), {
    call: true,
    main: true,
  });
});

test("Onboarding hides while a call is live", () => {
  assert.deepEqual(computeVisibility({ onboarding: true, callLive: true }), {
    call: true,
    main: false,
  });
});

test("Quitting hides both windows", () => {
  assert.deepEqual(
    computeVisibility({
      onboarding: true,
      settingsOpen: true,
      callLive: true,
      quitting: true,
    }),
    { call: false, main: false },
  );
});
