# Call-only app direction

## Product flow

The agent starts each call from its current session. TalkToMe shows a ring. The user answers it in the call surface. The active pill shows the session name, speech state, transcript, and call controls.

The main window shows onboarding and settings. After onboarding, TalkToMe stays in the menu bar while it waits for a call. The user opens settings from the menu bar. The main window has no conversation start control or message composer.

Onboarding must teach the call flow. The user checks the microphone, installs the agent skill, and then tries the sample call. The sample call is a demo. It shows the ring, the Answer control, and the End control. It uses the call colors and the control shapes. It keeps its own state. It does not send a request to the server. The demo identifies itself as a demo. When the demo ends, the app returns to the onboarding step.

The connection step shows one clear instruction: open the agent session and ask the agent to call. The final button closes setup, and its label describes that action. The button does not ask the agent.

The hidden window currently owns the microphone, audio, and event polling. This work must keep those functions active when the settings window closes. Closing settings must not quit TalkToMe. The Quit command must still stop the app.

## Call surface

The end-call button has a 36 px red circle with a 44 px click target. The answer button stays easy to press.

The call surface has two placements: Bottom and Top center. The user selects the placement in Settings. The setting is persistent, and the default is Bottom. The ring and the active pill both use the selected placement. A change moves a live surface at once.

The main process positions the window from the Electron `display.workArea`. The work area excludes the menu bar and the Dock. Electron gives no reliable camera housing geometry, so the app does not infer a physical notch. Top center means the top of the work area, below the menu bar. On a Mac with a notch, the menu bar is taller, so the pill sits below the camera housing. The app never claims to know where the housing is.

At the Bottom placement, the window keeps its bottom edge and grows upward when the transcript opens. At the Top center placement, the window keeps its top edge and grows downward, and the transcript sits below the pill. A drag is remembered. A placement change clears the remembered drag. A display change, a removed display, or a work area change recomputes the position from the current work area. A small work area clamps the window inside the work area.

### Placement limits

- Electron reports no notch size or shape. Top center cannot sit inside the camera housing. It sits below the menu bar.
- One setting applies to every display. Top center is not selected per display.
- A very small work area can clip the transcript. The pill controls stay on screen and usable.
- The top center placement needs a work area that is tall enough for the pill. The code clamps the window, so the position is always on screen.

## Checks

- A fresh install opens onboarding.
- The app stays available in the menu bar after onboarding.
- The agent can ring while no settings window is visible.
- The user can answer, speak, read the transcript, and end the call.
- The user can open and close settings during and after a call.
- The app can start a new call after the first call ends.
- The sample call answers and ends with no server request.
- The sample call returns to the onboarding step after it ends.
- The final setup button closes setup and does not ask the agent.
- The Settings screen saves Bottom or Top center, and the setting survives a restart.
- The ring and the active pill use the saved placement on the call display.
- At Top center, the transcript opens below the pill and the window grows downward.
- At Bottom, the transcript opens above the pill and the window grows upward.
- A placement change, a drag, a display change, and a work area change all keep the controls on screen.
