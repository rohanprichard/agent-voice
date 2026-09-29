# TalkToMe screens

Every screen in the desktop app, what is on it, and the exact copy.
Generated from `src/talktome/static/index.html` and `app.js`, so the wording is literal.

Screenshots of each screen are in `artifacts/ui/` and are named after the state keys below.

---

## Visual language

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| Background | `#edf0f4` | `#151b26` | window background |
| Sidebar | `#e4e9ef` | `#191f2b` | side panel |
| Surface | `#fafbfd` | `#1e2532` | composer and cards |
| Call surface | `#191f2b` | `#191f2b` | call bar and floating pill |
| User line | `#d7ff35` | `#d7ff35` | user speech and primary call action |
| Agent line | `#ff4fd8` | `#ff4fd8` | agent speech |
| End | `#c83d45` | `#ff4d4f` | end action |
| Muted text | `#566274` | `#a5aebd` | secondary text |
| Line | `#cbd4dd` | `#343e4e` | borders |

The app uses the system sans-serif font for headings, text, and controls.
The call bar uses the same navy color as the floating pill in both themes.
The light theme uses cool gray panels. The dark theme uses navy panels.
The two smooth lines appear in the app icon, the menu bar mark, the call bar, and the pill.

## 0. The window frame

A macOS Electron window, 1220 x 820, minimum 820 x 620, hidden-inset title bar, split into a
persistent **sidebar** (252px) and a **workspace**.

| Item | Copy | Notes |
| --- | --- | --- |
| Sidebar name | `TalkToMe` | sits after the traffic lights, in the 48px drag strip |
| Window buttons | — | macOS traffic lights, inset 22pt from the top-left |
| App menu | `TalkToMe`, `About`, `Settings…` (Cmd-,), `Quit` | `Settings…` opens the Settings screen |
| Edit menu | `Undo`, `Redo`, `Cut`, `Copy`, `Paste`, `Select All` | |
| View menu | `Reload`, `Toggle DevTools`, `Reset Zoom`, `Zoom In`, `Zoom Out` | |

There is no centred window title. The workspace has its own 48px drag strip above the page content.

### Sidebar

| Item | Copy | Notes |
| --- | --- | --- |
| Mark | the two-line circle | `/mark.svg`, right-aligned in the sidebar header |
| Name | `TalkToMe` | sans-serif, right-aligned. The left side stays clear of the traffic lights. |
| New conversation | `New conversation` | navy pill. Disabled only while a call runs. |
| List group | `Today` | only when a conversation has messages |
| List row | the first user message, truncated to 60 characters | time on the right. The current row has an accent line. |
| List empty | `Finished conversations will be listed here once the library lands.` | |
| Settings | `Settings` | opens the Settings screen |
| Agent chip | agent name, or `Connect an agent` | shows the status below the name. A disconnected chip has a border and an arrow. |

## 1. Screen: Conversation

`#page-room`. The default screen. Idle and running use the **same** layout: a conversation title,
a persistent call bar, a content area, and a composer. Only the content area changes.

### 1a. Workspace head

| Item | Copy |
| --- | --- |
| Title | the first user message truncated to 60 characters, or `New conversation` |
| Meta | the speech summary, e.g. `Whisper Small · Heart` |

### 1b. Call bar

One component in one slot, in two shapes.

**Before a call exists** the bar becomes a navy card.
It shows two lines, a heading, one line of context, and one button.

| Item | Copy |
| --- | --- |
| Heading | `Ready to talk.` |
| Context | `<agent name> is connected and ready when you are.`, `Connect an agent to begin.`, or the speech-not-ready line |
| Button | `Start a conversation`, or `Connect an agent` when no agent is connected. The second opens the connection screen instead of starting a call |

**Once a call starts, or a transcript exists**, it becomes a compact bar.

| Item | Copy |
| --- | --- |
| Line mark | 44px status indicator with two lines. The active line moves while a person speaks. |
| Status dot | lime while a call is running |
| Title | see the state table below |
| Description | see the state table below |
| Timer | `00:00`, in the bar, only during a call |
| Interrupt | icon only, `aria-label="Interrupt agent"` |
| Primary | `End conversation` |
| Level line | 2px rule under the bar, fills with microphone level |

| State | Title | Description |
| --- | --- | --- |
| Call running, agent speaking | `Agent speaking` | `Microphone paused. Select Interrupt to speak again.` |
| Call running, recognising | `Transcribing` | — |
| Call running, capturing | `Listening` | `Pause to send.` |
| Call running, no agent | `No agent connected` | `Use the connection link above.` |
| Call running, waiting | `Waiting for agent` | `You can speak again to change the request.` |
| Call running, mic off | `Microphone off` | `Enable your microphone, or type a message.` |
| Call running, ready | `Listening` | — |
| Call ended, transcript kept | `Conversation ended` | — |

### 1c. Empty content

Shown when the conversation has no messages. The block is centred between the workspace head and the
composer, biased slightly above the geometric centre, so the leftover space reads as one margin above
and one below rather than a void under the content.

| Item | Copy |
| --- | --- |
| Tagline | `Ideas, questions, refactors — just talk.` |
| Suggestions | three buttons, hidden until an agent is connected: `What does this project do?`, `Help me debug something`, `Make a small change` |

Choosing a suggestion fills the composer and focuses it. It does not send.

### 1d. Transcript

| Item | Copy |
| --- | --- |
| Author, user | `You` |
| Author, agent | the agent's name, or `Your agent` |
| Timestamp | local time, e.g. `3:07 PM` |
| Alignment | user messages right, agent messages left |
| Measure | messages capped at 88% of an 880px column |
| Scrolling | auto-scrolls to the newest message when already near the bottom |

### 1e. Composer (always present)

| Item | Copy |
| --- | --- |
| Microphone | a navy circle with a lime icon. It is gray when muted, off, or unavailable. `aria-label` is `Mute microphone`, `Unmute microphone`, or `Enable microphone` |
| Hidden label | `Message your agent` |
| Placeholder | `Type a message…` |
| Send | `↑`, `aria-label="Send message"` |
| Limit | 6000 characters |
| Privacy note | `Speech stays on this device`, `Microphone audio → ElevenLabs`, or `Local recognition · ElevenLabs voice` |

Sending with no call running starts one, without switching the microphone on. The microphone button
is the explicit way to start listening. A conversation cannot start without a connected agent: the
composer and the hero button both send you to the connection screen instead.

Screens 2 to 4 use the same colors, type, and control shapes.

---

## 2. Screen: Settings

`#page-setup`. Opens from the gear, from Cmd-,, or as onboarding step 1.

### 2a. Onboarding step 1

Setup takes the **whole window**: the sidebar is hidden, the column is centred at 880px, and the
footer actions are pinned to the bottom of the viewport. Neither setup step scrolls.

| Item | Copy |
| --- | --- |
| Eyebrow | `1 of 2` |
| Heading | `Speech setup` |
| Appearance select | `System theme`, `Light`, `Dark`; stays visible during onboarding |
| Close button | hidden during onboarding |
| Footer left | readiness line, one of `Ready to continue.`, `Allow microphone access, or set up later.`, `Set up speech recognition, or continue later.`, `Set up the agent voice, or continue later.` |
| Footer right | `Set up later` · `Continue` |

### 2b. Settings (normal use)

| Item | Copy |
| --- | --- |
| Heading | `Settings` |
| Appearance select | `System theme`, `Light`, `Dark` |
| Close button | `×`, `aria-label="Close settings"` |
| Note, while a call runs | `End the conversation before you change speech settings.` |
| Footer | none |

### 2c. Card: Speech recognition

| Item | Copy |
| --- | --- |
| Heading | `Speech recognition` |
| Label | `Recognition provider` |
| Provider options | `Whisper · Local`, `ElevenLabs · Scribe v2` |
| Model row | `Whisper Small` / `484 MB · Multilingual`, button `Download & use`, or `Active` when selected |
| Model row | `Whisper Base · English` / `145 MB · English`, button `Download & use` |
| Download state | label `Download in progress`, `Load the speech model`, or `Download failed`; percent `42%`; detail `203 MB of 484 MB` or `Please wait.` |
| Label | `Microphone` |
| Microphone select | `System default`, then each detected input device by name |
| Permission granted | `Microphone allowed` |
| Permission denied | `Access denied in system settings.` |
| Permission button | `Allow microphone`, or `Please wait…` while asking |

The backend also sends a `description` and a `recommended` flag for each Whisper model. The interface does not display either one yet.

### 2d. Card: Agent voice

| Item | Copy |
| --- | --- |
| Heading | `Agent voice` |
| Label | `Voice provider` |
| Provider options | `System voice · Local`, `Kokoro · Local`, `ElevenLabs · Flash v2.5` |
| Kokoro block | `Kokoro 82M` · `142 MB`; `English voices. Works offline after download.` |
| Kokoro button | `Download Kokoro`, `Downloaded`, or `Please wait…` |
| Kokoro progress | `42% · 60 MB of 142 MB`, or `Load the voice model…` |
| Label | `Voice` |
| Voice select | `Provider default` when the provider has one, then each voice as `Name · Language` |
| Preview button | `Preview voice` (speaks `This is the selected voice.`) |

### 2e. Card: ElevenLabs (full width, shown when configured or selected)

| Item | Copy |
| --- | --- |
| Heading | `ElevenLabs` |
| Body | `ElevenLabs receives your audio for recognition and the agent's reply text for speech, when selected. Service charges can apply.` |
| Label | `API key` |
| Placeholder | `Enter your ElevenLabs API key` |
| Button | `Connect` |
| Checkbox | `Remember key in the system keychain` |
| Status, none | `No key connected.` |
| Status, session only | `Key connected for this app session.` |
| Status, remembered | `Key connected. The system keychain stores the key.` |
| Remove button | `Remove key` |
| Note | `Without Remember key, the key stays in memory until you close the app. The key needs access to voices and the selected speech services.` |

---

## 3. Screen: Connect an agent

`#page-connect`. Opens from the agent link, or as onboarding step 2.

### 3a. Onboarding step 2

| Item | Copy |
| --- | --- |
| Eyebrow | `2 of 2` |
| Heading | `Connect an agent` |
| Close button | hidden during onboarding |
| Footer | `Back` · `Connect later` · `Open conversation` |

### 3b. Normal use, no agent

| Item | Copy |
| --- | --- |
| Heading | `Connect an agent` |
| Close button | `×`, `aria-label="Close agent connection"` |
| Status | `No agent connected` |
| Disconnect button | hidden until an agent connects |

### 3c. Card: Install for your agents

| Item | Copy |
| --- | --- |
| Heading | `Install for your agents` |
| Action | `Check again` |
| Body | `TalkToMe adds its own tools to the agent clients on this Mac. Open a new agent session afterwards so it picks them up.` |
| Row, not found | `<client name>` / `Not found on this Mac` |
| Row, ready | `<client name>` / `Ready to add`, button `Install` |
| Row, installed | `<client name>` / `TalkToMe tools are registered`, button `Reinstall` |
| Row, not detected | `<client name>` / `Not found on this Mac` |

Registration uses each client's own mechanism, so every client keeps its own format:

```sh
codex  mcp add talktome --env TALKTOME_URL=… --env TALKTOME_DATA_DIR=… -- <python> -m talktome.mcp_server
claude mcp add talktome -s user -e TALKTOME_URL=… -e TALKTOME_DATA_DIR=… -- <python> -m talktome.mcp_server
```

DeepSeek Harness has no `mcp add`, so the app appends a patch-layer row to
`~/.dsh/profiles/web/cordis.patch.yml` instead. The MCP client ships inside the dsh installation,
so no package install is needed, and reinstalling replaces the row rather than duplicating it.

### 3d. Ask your agent to join

Installing is only step one: the agent still has to start and connect. This card is always visible
so the next action is obvious.

| Item | Copy |
| --- | --- |
| Heading | `Ask your agent to join` |
| Copy button | icon only, `aria-label="Copy instruction"` |
| Body | `Open a new agent session and paste this so it connects to TalkToMe.` |
| Prompt | the connect instruction, copied as one clean line |

The footer reports what is still needed: `Install TalkToMe for an agent to continue.`,
`Open a new agent session and paste the instruction above.`, or `<agent name> is connected.`
`Open conversation` enables once an agent is **installed or connected** — setup should not trap
someone whose agent is not running yet.

### 3e. Add it by hand instead

The manual route lives behind a disclosure so the step fits the window.

| Item | Copy |
| --- | --- |
| Summary | `Add it by hand instead` |
| Default | folded, in setup and in normal use |

Inside it:

#### Card: Add the connection

| Item | Copy |
| --- | --- |
| Heading | `Add the connection` |
| Copy button | icon only, `aria-label="Copy configuration"`, `title="Copy configuration"` |
| Body | `Add this configuration to your agent's Model Context Protocol (MCP) settings.` |
| Code block | the MCP JSON with the real Python path and data directory; click or press Enter to copy, `aria-label="Copy configuration code"`, `title="Click to copy"` |

#### Card: Other connection methods

| Item | Copy |
| --- | --- |
| Heading | `Other connection methods` |
| Body | `Use the authenticated HTTP interface at <url>. See docs/AGENT_API.md for the protocol.` |
| Button | `Copy local access token` |

### 3f. Agent connected

- Status becomes `<agent name> is connected`.
- `Disconnect` button appears.
- `Open conversation` becomes enabled during onboarding.

---

## 4. Screen: Connect to this device

`#pair-screen`. Appears only when the window cannot authenticate with the local server.

| Item | Copy |
| --- | --- |
| Heading | `Connect to this device` |
| Body | `Open the desktop app, or enter the local server token.` |
| Label | `Local token` |
| Input | password field |
| Button | `Connect` |

---

## 5. Transient overlays

| Overlay | Copy | Behaviour |
| --- | --- | --- |
| Alert | varies, see below | fixed near the top, dismiss button `×`, `aria-label="Dismiss message"` |
| Copy toast | `Copied` | fixed near the bottom, disappears after 1.6s |

### Alert messages

| Trigger | Copy |
| --- | --- |
| No speech detected | `No speech was detected. Speak closer to the microphone, or type your message.` |
| Reply audio failed | `The reply audio did not play. The text is in the conversation.` |
| Reply audio error | `The reply audio did not play. <error>` |
| Event stream dropped | `The local connection stopped. TalkToMe will try to connect again.` |
| Microphone blocked | `Microphone access is off. Allow microphone access in system settings, then enable it again.` |
| Microphone failed | `The microphone did not start. <error>` |
| Permission refused | `Allow microphone access in system settings, then try again.` |
| Permission error | `The microphone is unavailable. Examine its connection and system permissions.` |
| Speech not ready | `Speech recognition is not ready. You can type now, or open Settings to examine setup.` |
| Clipboard blocked | `The clipboard is unavailable. Select the text, then copy it.` |
| Request failed | the server's message, or `The request failed (<status>).` |

---

## 6. Screen: the floating call surface

A separate frameless, transparent window that appears while a call is live. The
application window hides for the length of the call and TalkToMe stays in the
menu bar. Its own stylesheet gives it the same navy material on any desktop background.

While the call is ringing the pill shows a different set of controls, because mute
and transcript mean nothing before someone has answered:

| Element | Copy | Notes |
| --- | --- | --- |
| Bell | none | lime circle, pulsing; the one place the surface asks for attention |
| Caller | the name passed with `--name`, else the project folder | beside `wants to talk` |
| Answer | `Answer the call` | lime circle, handset |

There is no decline control. A ring is answered or it stops on its own after about
ten seconds, which is the whole of the window a user has to notice it, decide, and
reach the pill.

Once answered, the pill becomes the call surface below and the greeting is heard.

| Element | Copy | Notes |
| --- | --- | --- |
| Mute | `Mute microphone` / `Unmute microphone` | icon only; the glyph swaps to a crossed microphone and sits in a red circle when muted |
| Threads | none | the user's line in `#d7ff35`, the agent's in `#ff4fd8`; the state is communicated by the lines, never by a label |
| Status | `The call stopped` | only shown on failure. Connecting is carried by slower, dimmer threads |
| Transcript | `Transcript panel` | a disclosure control: one name, with `aria-expanded` reporting state |
| End | `End call` | red circle with a handset |
| Transcript panel | `Transcript`, `Nothing said yet.` | opens upward over the pill; each line is labelled `You` or the agent's name |
| Transcript close | none | `aria-label` only: `Close transcript` |

The controls are icon only, with the name carried by `aria-label` and a tooltip.
At this size a label and a glyph fight for the same 56 pixels of height.

The pill is 340x56 and the window is 360x76: the pill plus a 10px transparent ring
for its drop shadow, and nothing else. Every transparent pixel still takes the
mouse, so a larger window would swallow clicks meant for the application
underneath. The material is opaque, because this floats over the user's work and
seeing it through the controls made both the text and the threads harder to read.

The window is movable. Dragging anywhere on the pill except a control moves it, and
the position is remembered: opening the transcript grows the window upward from the
bottom edge the user left, rather than snapping back to the centre of the display.

The window grows upward to 320px when the transcript opens, so the pill's bottom
edge does not move. Sizes and the bottom margin live in `desktop/geometry.cjs`,
where they are unit tested against work areas including second displays, displays
too small to hold the pill, and a remembered position left off screen by an
unplugged display.

The main window sends one speech flag for each person. The pill uses these flags to change each line.
The surface also sets `data-speaker` to `none`, `user`, `agent`, or `both`.

Each line moves faster when its person speaks. The lines move in opposite directions.
The new curve has three smooth bends. The lines have small differences in their shape. Their travel is slow.
Speech makes the active line taller. The other line stays visible but less bright.

The canvas draws both lines at the device pixel ratio.
The lines fade at each end and cross near the center. A quiet line still moves a small amount.

---

## 7. Native surfaces

| Surface | Copy | When |
| --- | --- | --- |
| Menu bar item | `TalkToMe` | whenever the app is running; opens the window, ends a live call, quits |
| Microphone permission dialog | macOS system wording | when `Allow microphone` is used during setup |
| Quit confirmation | system wording | only if the local server stops unexpectedly |

---

## 8. State keys used by the screenshot script

`scripts/ui-shot.mjs` renders each of these to `artifacts/ui/<key>.png`.

| Key | Screen |
| --- | --- |
| `room-empty` | 1a-1c, no call |
| `room-needs-model` | 1b, speech not set up |
| `room-agent` | 1b + 1d, waiting for the agent |
| `room-ended` | 1b, call ended |
| `settings` | 2b + 2c + 2d |
| `settings-downloading` | 2c, download in progress |
| `settings-kokoro` | 2d, Kokoro selected and downloaded |
| `settings-elevenlabs` | 2e, key configured |
| `onboarding-speech` | 2a |
| `connect` | 3b + 3c + 3d |
| `connect-agent` | 3e |
| `onboarding-connect` | 3a |
| `pair` | 4 |

Every key also has a `-dark` twin except `settings-downloading`, `connect-agent`, and `onboarding-connect`.

---

## 9. Not built yet

From the agreed product direction:

- A conversation library: past conversations grouped by date, pick one up, delete one.
- Saved agents: Claude Code, Codex, and others as profiles you switch between per conversation.
- Choosing an agent when starting a conversation, and the app launching it.
- Picking a working folder (git repository) before the agent runs.
- Screen capture and drawing overlays.

From the reference design, still to do:

- Transcript tool rows: `Reading src/auth/…`, `Editing 3 files`, `Running tests…`. These need a new
  agent event, because the protocol has no way for an agent to report tool activity today.
- Settings navigation: `General`, `Voice`, `Agent`, `Shortcuts`, `Advanced`, with rows rather than cards.
- Settings toggles: `Launch at login`, `Keep in menu bar`, `Start listening with shortcut`.
- The talk shortcut. The reference shows `⌘Space`, which macOS reserves for Spotlight, so it needs a
  different binding and must be opt-in.
- The brand sheet: marketing wordmark, script taglines, and the logo lockup.

From the floating call surface brief, still to do:

- Choosing which display the pill appears on, and a way to send it back to the
  bottom centre after dragging.
- Answering a ring anywhere but the pill. If the pill is not visible there is no way
  to take a call except waiting for it to stop and asking the agent again.
- Telling the agent when nobody answered, so it is not left assuming a call it never
  got to have.
- A Settings switch for the floating surface instead of the
  `TALKTOME_FLOATING_CALL` environment variable.
- Choosing which microphone, and a per-conversation voice, from the surface itself.
