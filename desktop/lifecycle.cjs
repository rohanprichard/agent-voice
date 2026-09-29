"use strict";

// Window visibility for the call-only application.
//
// The main window shows onboarding and settings only. After setup it waits in
// the menu bar and stays alive, because the hidden renderer owns the microphone,
// the audio, and the event polling. The call window shows the ring and the
// active call. This decision is kept out of Electron so the rules can be tested
// without starting the application.

/**
 * What each window must show.
 *
 * The main window shows only when it has a reason to: setup is not complete, or
 * the user opened settings. A live call hides the main window so the pill has
 * the screen. A call that ends does not show the main window again.
 *
 * `dismissed` is true after the user closes the window. It stops setup from
 * showing the window again until the user opens settings or setup reports again.
 * `callLive` is true for a ring and for an answered call.
 */
function computeVisibility({
  callLive = false,
  onboarding = false,
  settingsOpen = false,
  dismissed = false,
  quitting = false,
} = {}) {
  const call = Boolean(callLive) && !quitting;
  const main =
    !quitting &&
    (Boolean(settingsOpen) ||
      (Boolean(onboarding) && !callLive && !dismissed));
  return { call, main };
}

module.exports = { computeVisibility };
