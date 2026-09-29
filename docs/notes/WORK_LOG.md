# Work log

## September 29, 2026: Expand approval cards and correct installation paths

Approval cards now show the full request when the user selects Full request.
The expanded text retains all request fields and command line breaks.
The details scroll within the card. The Allow once and Deny buttons stay visible.
A new request closes the details. State updates for the same request keep the details open.

The Python wheel now includes the TalkToMe skill from its source file.
The skill lookup supports the Python package, frozen app, and repository.
Remote setup now sends the custom relay file path to both initialization and service installation.
The printed commands also retain that path.

Syntax and lint checks passed. No automated tests, app build, or calls ran.
The Hermes shell stall remains unresolved. The earlier command stopped before it called TalkToMe.

## September 28, 2026: Make the call skill visible to Hermes and OpenClaw

The installer previously wrote the TalkToMe skill only to the Codex directory.
Hermes therefore found no call instructions when it searched its skills and tools.
The installer now includes existing Hermes and OpenClaw profiles and reports each host's skill state.
The skill explains shell-based calls and gives explicit cooperative commands for Hermes and OpenClaw chats.
This path uses the current chat and needs no Hermes API server.

The local Hermes, OpenClaw, and Codex skill copies now contain these instructions.
The OpenClaw skill uses its default shared directory. No local OpenClaw configuration existed before this installation.
Remote hosts still need their own skill installation and a separate transport to the laptop.
The installed command lists `--agent hermes`, cooperative mode, `listen`, and `reply` in its help output.
No call, app build, or automated test ran for this change.

## September 28, 2026: Overlap input work and separate speech delivery

The first Smart Turn check now starts an early Scribe commit.
The client holds later audio until the user resumes speech or the turn ends.
It joins resumed segments before it sends one message to the agent.
Input errors retain the full recording for batch transcription.

A bounded speech worker now reads messages in their original order.
The agent reader no longer waits for each speech message to finish.
ElevenLabs output uses a call connection with a separate context for each message.
Context close operations do not block input cancellation. Audio retains its original call and playback epoch.

The text threshold decreases to 50 characters. Capture blocks decrease to 512 samples.
The Codex rollout reader uses macOS file notifications, with polling as a fallback.
The existing playback lead remains unchanged because earlier calls lost the start of speech.
The observer research found no documented subscription method that avoids thread start or resume.

The app retains 200 private timing records outside the transcript.
The authenticated timing endpoint returns stage durations and accepts late reports for retained turns.
Static checks passed. No automated tests, app build, or calls ran.
[Call latency](../LATENCY.md) gives the behavior, API, and measurement limits.

## September 27, 2026: Add local Smart Turn

Smart Turn v3.2 now checks pauses beside live ElevenLabs transcription.
The microphone retains the recording while the model runs. Resumed speech cancels the old decision.
The app waits for incomplete speech, with a three-second silence limit and the existing recording limit.
Model failures use the fixed-pause rule. Settings supports disable, status, and download retry.

The model download uses a pinned revision and SHA-256 digest. No new runtime dependency is required.
The pinned graph ends with Sigmoid. This corrects the earlier claim that its `logits` output needs conversion.
[Smart Turn](../SMART_TURN.md) records the model interface, pause settings, diagnostics, and limits.
Static checks passed. No model inference, automated tests, app build, or live calls ran.


## September 27, 2026: Agent connections and interruption context

The source now supports cooperative call commands for Claude and other shell hosts.
Experimental adapters connect existing Hermes API sessions and OpenClaw Gateway sessions.
Host capability checks reject unsupported connections. Private configuration stores host tokens.
The call skill requires subagents for extended work unless the user requests direct work.

Codex now keeps a queue proxy for each call. It falls back before input submission
or after an explicit unsupported-method response. It does not resend uncertain input.
No measurement yet shows the time saved in a real call.

The microphone can pause speech during a sustained input signal. An empty transcription
resumes output. A confirmed interruption clears old audio. Playback receipts and provider
alignment produce a conservative text estimate for the next agent input. The estimate
does not remove text from host history or prove what the user heard.

The implementation rejects stale playback epochs and serializes cooperative replies.
The approved native notch glow and call surfaces remain unchanged.
Ruff, Python syntax, JavaScript syntax, and whitespace checks passed.
No tests, app build, or real calls ran for this checkpoint.
[Agent support](../AGENT_SUPPORT.md) gives commands, limits, and the remaining live checks.
Smart Turn remains a separate integration step. Its published recordings can support
initial checks without a new speech collection or model training.


## September 26, 2026: Integrate the movable native call surface

The native helper keeps the approved notch glow. The separate black pill supports
dragging by its background or timer. The transcript keeps its own position and
uses the same black surface. Its header remains a drag area.

Electron waits for the native panels to report readiness before it hides the old
pill. A helper failure restores the fallback controls. The native timer uses the
call start time. Native ringing stops after its time limit. The transcript opens
below the pill and stays closed after the user closes it. Display changes keep
dragged controls inside a visible work area.

The standalone source is in a separate `notch-glow` repository.
Its Git history includes commits `2ec61ad` and `3ced1d4`. It contains a Finder app
bundle and the MIT license. Its source keeps the approved glow geometry and colors.
The standalone build and full TalkToMe build completed. The app package includes
the server and native helper. No interactive checks or real calls ran.

## September 26, 2026: Position the compact pill below the glow

The pill now starts 64 pt below the measured camera depth, centered on the camera.
The connected size decreases from 320 by 64 pt to 280 by 56 pt.
Buttons decrease from 34 to 30 pt, with smaller symbols and incoming text.
Black remains at 96% opacity. The notch glow keeps its current geometry.
The roadmap now lists the app integration steps and release checks.
The user will examine the preview. The full app build remains pending.

## September 26, 2026: Move the controls into a bottom pill

The notch keeps its glow and has no call panel. A separate native panel shows
the call controls at the bottom center of the display, above the Dock.
The pill uses black at 96% opacity. It shows the timer and three call buttons.
The incoming state shows the caller name, Answer, and Decline.
The pill hides after the call ends. The silent preview uses the same controls.

## September 26, 2026: Match the selected call panel reference

The connected panel now shows a centered call timer above the controls.
Its width is at least 260 pt, or 40 pt wider than the measured camera area.
The panel extends 98 pt below the camera. Its dark surface increases from
78% opacity at the top to 96% at the bottom. The lower corners remain clean.
The timer starts when the native surface enters a connected state.
It continues through speech and mute states. It resets when the call ends.
The glow geometry remains unchanged. The user will examine the silent preview.

## September 26, 2026: Use a colored edge and call panel A

The thin edge now uses the glow color without a white mixture. The curve and
halo keep their positions and dimensions. The project selected call panel concept A.
The panel now has opaque dark surfaces and clean lower corners. The side and
bottom opacity fades are removed. The connected panel uses a minimum width of
236 pt, with 62 pt between button centers. The incoming panel uses a 336 pt width.

## September 26, 2026: Shorten the glow and strengthen its colors

The glow now ends 160 pt beyond each camera side. Its outer 95 pt fades to
transparent. The six color presets use more saturated colors. The curve, lower
halo, and call panel keep their previous geometry. Call panel concepts are a
separate visual review, with no new panel design applied to the app.

## September 26, 2026: Extend the lower halo and darken the panel center

The glow has an additional soft halo 6 pt below its path. The bright edge and
hardware curve keep their positions. The call panel center is now opaque black.
Opacity fades within 26 pt of the sides and 18 pt of the lower edge.
The buttons remain opaque. The silent preview is the review artifact.

## September 26, 2026: Extend the glow to the screen edges

The horizontal glow now sits 0.5 pt below the display top and spans the full width.
It fades toward each screen edge. The black fill remains only around the central
shoulders. This removes the short black bars above the outer wings.
The call panel remains, as the user requested. The silent preview compiled.
The user will examine this version on the physical display.

## September 26, 2026: Keep the glow at the hardware depth

The user supplied a physical display photo. It showed that the prior curve added
black space below the hardware notch. The lower glow now sits 0.5 pt below the
measured camera depth. The shoulders extend sideways. The 27 pt downward extension
is removed, and the call controls moved upward by 26 pt.

The native preview compiled. I examined the Hover and Connected screenshots.
The preview uses the same curve in both states. The thin core stays outside the
measured camera rectangle. The black mask covers the inner part of the broad glow.
The physical seam still needs examination on the display. No real call ran.

## September 25, 2026: Add tapered notch shoulders

The user supplied close views of the reference. The notch now has smooth shoulders
that turn inward below the camera. The horizontal light and black fill fade at
both wing ends. The lower panel decreases to 68% opacity at its bottom.

I compiled the silent preview and examined screenshots of Thinking and Hover.
The first curve was too shallow, so I made the shoulders steeper. A sampled
geometry check found 9.55 pt of clearance from the camera rectangle on this Mac.
The preview remains separate from real calls.

## September 25, 2026: Add a silent native notch preview

The native panel now draws the glow at the camera extension. The lower control
panel has no luminous border. The user requested more spread and larger curves.
The black extension adds space around the camera area, and the halo fades across
a 36 pt radius. The lower corners use a 20 pt curve. Call buttons use 34 pt circles.

`npm run build:notch-preview` builds a separate preview app. It has local state
and color controls. It does not start calls or use the microphone or network.
App screenshots showed the incoming, connected, speaking, and thinking states.
The Answer, microphone, and transcript controls changed the local preview.

The main app did not receive a new build during this pass. The physical seam and
live call integration still need examination. The [preview note](research/NOTCH_SILENT_PREVIEW.md)
gives the build and use steps.

## September 25, 2026: Keep the glow at the top

The setup panel no longer casts a colored shadow around its full edge. A soft
light now fades from the dark top center. Settings uses the same light. I inspected
both windows in an isolated app run. The lower edge had no colored glow.

## September 25, 2026: Remove the second notch and match Settings

The setup window now starts below the menu bar. It does not draw a black notch
over the camera housing. Its first top edge had a thin glow. I shortened the setup text
and changed the local model link to Customize. Settings now uses the same dark
surface and the selected glow color. It keeps the speech, voice, and call controls
in two columns. The desktop setup window owns the setup steps.

I inspected the welcome and key screens in an isolated app run. I also inspected
Settings and the agent page. The glow changed when I selected Blue. I did not
build the packaged app. The user will request that build later.

## September 25, 2026: Add setup below the notch

The [roadmap](ROADMAP.md) now records the notch states and the setup order.
A separate setup window sits at the top center of the screen. It shows six steps:
welcome, microphone, ElevenLabs key, agent skill, glow color, and final instructions.
The local model link opens Settings. Closing Settings returns to the same setup step.

The first version used the screen bounds on macOS and drew an estimated cap.
Electron did not give the app the camera housing shape. The later change above
removed that cap and moved the window to the work area.

I inspected screenshots of the welcome, microphone, key, agent, color, and final
steps in an isolated app run. The key step initially exceeded the window. I reduced
its height. I also fixed color choices that the content security policy hid.
The chosen color now changes the setup glow. The call surface redesign will use
that saved color in a later pass.

## September 25, 2026: Finish Codex speech and simplify the transcript

The Sep 25 call stopped speaking after Codex used a file command. Codex wrote
`parsed_cmd` as a list. The attached adapter called `.strip()` on that list and
stopped the turn reader. The Codex rollout still had the final answer. The adapter
now reads both list and text command forms. Thus, it can reach the final answer.

The hang-up command ended the call with `status: idle` and exit code 0. Its result
still showed the old turn-reader error. The app now clears that error when it
closes the agent session. The transcript no longer shows timing data. Its default
width is 360 px, and the user can still resize it.

The [terminal delivery note](research/CODEX_TUI_DELIVERY.md) maps the delay from
the call transcript to Codex. The ended call kept no timing marks, so the note
does not assign its reported delay to a stage.

## September 25, 2026: Stream ElevenLabs speech input

The existing microphone now sends PCM audio to Scribe Realtime while the user
speaks. The local server gives the browser a single-use token. The ElevenLabs
API key stays on the server. The call transcript shows partial text, but Codex
gets only one committed message after the current pause rule ends the turn.

The microphone keeps the audio for recovery. If the live connection fails or
takes too long, the app sends the saved audio through the batch path. Whisper
still uses the batch path. The app closes the live connection when the call ends
or the microphone discards a short clip.

This change does not remove the delay after text enters the call transcript.
The queue timing panel measures that part. A real call and the app build did not
run because the user will build after the source changes are complete.

## September 25, 2026: Keep the call visible and finish each spoken message

The Codex turn record contained the final answer. The call used ElevenLabs for
speech input and output. The voice socket stayed open across tool work, so the
provider could wait for more text after a completed status message. The app now
opens a voice socket when a message arrives. It closes the socket when that
message ends. Thus each status message and the final answer can finish on its own.
The app also reports a voice socket that closes early or takes too long to finish.

The menu bar showed an active call after the pill disappeared. The exact window
event is unknown. The main process now checks for a hidden call window once each
second and shows it again. The menu bar also has a Show call action. A click on
the menu bar icon shows the call while it is active. A short
failure of event polling no longer stops audio that already plays.

The call timing panel now shows when the queue command starts and when the
terminal reads a queued message. The app also finds the Codex command before
the first spoken message.
TalkToMe checks the Codex turn record every 0.1 seconds instead of every 0.4
seconds. This change can reduce the wait before TalkToMe sees an agent reply.
The Codex command still decides when the terminal shows a queued message.

## September 25, 2026: The ring stops, the panel resets, and the transcript resizes

An ignored ring kept playing its tone. The main process hid the call window
after the ring ended, but it did not send the idle state to the window on the
no-call branch. The hidden renderer never stopped its own tone. The main process
now sends the idle state before it hides the window. The surface also stops the
tone after twelve seconds and when the window becomes hidden. Thus a missed
event cannot leave a ring playing. A new ring starts the tone again.

The call window stays open between calls, so the last transcript showed during a
new ring. The main process now closes the transcript and clears the drag anchor
when a call starts or ends. The surface keeps only the messages whose call id
matches the current call. Old messages no longer appear for a new call, and the
active call keeps its own transcript.

The transcript panel is now resizable. The user drags a grip at the free corner.
The panel changes width and height. The window grows with the panel and stays
inside the work area. The pill keeps its size. At the bottom placement the panel
grows upward. At the top center placement the panel grows downward. The chosen
size stays for the rest of the run. The ring state never shows the panel.

The main process owns the window, so the surface sends the requested size over
the bridge. The main process clamps the size to the work area and sends the
applied size back. The surface draws that size. The geometry lives in
`desktop/geometry.cjs` as `transcriptBounds`.

Limits: the desktop tests and a real call did not run, because this task must not
start the app. The window is never narrower than the pill, so a transparent band
around the pill remains. The call window keeps its last bounds until the next
show, because it resets the bounds while it is hidden.

## September 25, 2026: Call surface placement

The Settings screen now offers the call surface placement: Bottom or Top center.
The default is Bottom. The choice is saved in the renderer storage and reported
to the main process over the bridge. The ring and the active pill both use it. A
change moves a live surface at once and clears a remembered drag.

The geometry keeps one rule for each placement. At Bottom the window keeps its
bottom edge and grows upward when the transcript opens. At Top center the window
keeps its top edge and grows downward, and the transcript sits below the pill.
The call surface uses flex order and a matching opening animation.

The position comes from the Electron `display.workArea`. The work area already
excludes the menu bar and the Dock. Electron reports no camera housing geometry,
so the app does not infer a physical notch. Top center means the top of the work
area, below the menu bar. A display change, a removed display, or a work area
change recomputes the position from the current work area. A small display clamps
the window inside the work area, so the pill controls stay usable.

`desktop/geometry.cjs` now takes a placement and maps an unknown value to Bottom.
New checks cover the top center bounds, the downward transcript growth, the drag
anchor, a second display with a negative origin, an unknown placement, and a
small work area. Source checks cover the Settings control, the bridge, the main
process handler, and the call surface layout.

Settings does not stop reply audio during a call.

Checks passed: 266 Python tests, 113 JavaScript tests, and Ruff. The package
build made `dist/app/TalkToMe-0.1.0-arm64.dmg`. The Electron smoke tests and a
real call were not run, because this task must not start the app.

## September 25, 2026: The main window shows setup and settings only

The main window now shows onboarding and settings only. After setup, the window
hides and the app waits in the menu bar. The hidden renderer stays alive because
it owns the microphone, the audio, and the event polling.

The main process decides window visibility in one place. `desktop/lifecycle.cjs`
holds the rules, and new unit tests cover them. A live call or a ring shows the
pill. A call that ends does not show the large window.

Closing settings hides the window. The app does not stop. The Quit command still
stops the app. The Settings menu item, the menu bar item, and a second launch all
open settings.

The conversation start control and the message composer are gone from the main
window. The agent starts every call. The pill keeps the transcript.

The red end-call circle is now 36 px. Its click target is 44 px.

The onboarding final action now closes setup. Its label describes that action,
and the connection step gives one clear instruction: open the agent session and
ask the agent to call.

The connection step also has a sample call. The sample call is a demo. The user
selects Answer, then End. The demo uses the call colors and the control shapes.
It keeps its own state in `demo-call.js`, sends no request, and returns to the
onboarding step when it ends. The demo source checks lock this down.

Checks passed: 96 JavaScript tests. These include the new demo state machine
tests and the updated window-control checks. The Electron smoke tests were
updated but not run, because this task must not start the app. Ruff did not run,
because the sandbox blocked the uv cache. The notch placement is left for a
second task.

## September 24, 2026: Agent labels and default pause

An attached call now uses the session name on the ring and the call pill. The transcript uses the name from the connected agent adapter. The default pause is 0.9 s. Quick stays at 0.7 s, and Patient stays at 1.8 s.

## September 24, 2026: Call pause, end control, and session name

The user reported that the microphone ends a phrase during a pause. The old rule waited 0.45 s after long speech. The new default waits 1.2 s. The settings also give a 0.7 s Quick mode and a 1.8 s Patient mode.

The pill now has a Stop reply control. The control stops audio and sends `/call/interrupt`. The app pauses the microphone during playback, so speech does not stop a reply. [Voice turn research](research/VOICE_TURN_TAKING.md) records the limits of automatic interruption and the Smart Turn test gap.

The pill's End call control now releases an attached session. Thus, a new call can ring after the user ends the first call. A call uses the Codex session name from the local state database when it exists. The `--name` value and the project folder remain fallbacks.

The pill uses the same dark surface and call colors as the ring. Its controls use round surfaces. The build produced `dist/app/TalkToMe-0.1.0-arm64.dmg`. The checks passed: 265 Python tests, 61 JavaScript tests, and Ruff. No live call ran in this pass.

## September 25, 2026: The turn detector is the right model, and TTS cannot test it

The research said the cheap well-evidenced win is an audio-only turn detector rather
than a streaming recogniser, so the model was taken apart before anything was wired.

**Everything about it fits.** [Pipecat Smart Turn
v3.2](https://huggingface.co/pipecat-ai/smart-turn-v3) is BSD-2, 8M parameters, and
**8.3 MB** as int8 ONNX — measured, not read. It runs on `onnxruntime`, which the app
already ships for Kokoro, so it adds no native dependency and no download of the size
Whisper needs. It is a Whisper Tiny encoder with a linear head, so it wants the same
log-mel input as everything else here: `input_features` shaped `(1, 80, 800)`, eight
seconds at ten-millisecond hops, with the **last** eight seconds kept. Its own
published benchmark is 92.63% accuracy over 31,527 samples and 23 languages, and
English is 94.26%. It needs no macOS permission, which is what ruled Apple's
recogniser out.

Two interface details worth writing down because they cost time to find. The output is
named `logits`, not a probability, so the published `inference.py` — which is written
against v3.1 and treats the output as a probability directly — does not describe this
version's head. And `transformers` is not needed for the mel spectrogram:
`faster_whisper.feature_extractor.FeatureExtractor` already produces it, and comparing
the two gives a mean absolute difference of 0.49 in the features and a change of less
than 0.04 in the model's output, so the cheaper one is good enough.

**Then it could not be evaluated, and the reason is worth having.** Run against
synthesised speech, the model does not discriminate: a finished sentence scores 0.57
and a plainly unfinished one 0.72. The temptation is to blame the preprocessing, and
that was checked first — the reference `WhisperFeatureExtractor` gives 0.566 and 0.721
for the same two clips, so the features are not the problem. The audio is. `say`
produces declarative falling intonation on every sentence regardless of grammar, and
this model is reading prosody rather than grammar. Every clip it is given sounds
finished, so it answers that they are.

So a turn detector cannot be tested with text-to-speech, and there is no recorded
conversational audio in this repository to test against. That is the blocker: not the
model, not the licence, not the dependency — a validation set. The next step is either
the published test set (`pipecat-ai/smart-turn-data-v3.1-test`) or a few real
recordings, and until one of those exists there is no honest way to say this works,
however good the model is on paper.

Nothing was wired and nothing was shipped. The measurement that would decide where the
seconds actually are — end of speech to first audible syllable, broken down by stage —
is also still not taken, and it remains the number worth having before either the turn
detector or a streaming recogniser is built.

## September 25, 2026: What streaming Whisper actually costs

The recogniser is built and works. `hearing.Ear` is fed audio as it arrives, runs
Whisper over what has been heard, and offers only the words two consecutive runs
agree on — the standard way to get partials out of a batch model. Sixteen tests cover
the agreement, the endpointing, and the ways it can fail. Against the real model and a
real 3.4-second clip it produced `partial 'Hey can you hear'` and then the exact
final text.

Then it was measured, and the measurement changes the recommendation.

| model | CPU per run | quality |
| --- | --- | --- |
| `small` | ~2.3 s | — |
| `base.en` | **1.41 s** | exact |
| `tiny.en` | **0.86 s** | exact, and punctuates |

The number that matters is not the one per run but its shape: **the cost is almost
independent of how much audio there is.** A one-second buffer costs 1.21 s of CPU and
a six-second buffer costs 1.88 s, because Whisper encodes a padded thirty-second
window every single time. Whisper is a batch model and no amount of wrapping changes
that; VAD makes no difference to it, and beam width only moves it between 1.4 and
2.3 seconds.

So streaming means paying that per run, and a partial every second means paying it
every second. On `base.en` that is **~1.4 cores, continuously, for as long as the user
is talking**, to buy back the 0.55–1.1 s of silence detection and the 0.32–0.47 s of
batch transcription. On `tiny.en` it is 0.86 of a core. Both are real, sustained load
that competes with the agent process on the same machine, in exchange for under a
second on short turns.

That is a bad trade, and it is now a measured one rather than an argument. It is also
the answer to why AgentCall's recogniser is hosted: a model built for streaming — a
chunked encoder like Parakeet or sherpa-onnx's Zipformer — costs a fraction of this
because its encoder sees only the new audio. Streaming Whisper re-hears the whole
utterance every time by construction.

What is committed here is the part that is right and cheap: `hearing.Ear`, which is
transport-agnostic and takes any `transcribe(samples, prompt)`, and `Speech.listen`,
the greedy single-run transcription it drives. The transport is not built. If the
decision is to have partials, the next thing to price is a chunked-encoder model, not
a WebSocket around this one.

## September 25, 2026: Apple's recogniser works, and cannot be dropped in

The question was whether a streaming recogniser would fix the wait between speaking
and being heard. Whisper cannot answer it — `faster_whisper.WhisperModel` exposes
`transcribe`, `encode`, `detect_language` and nothing that yields partial results —
so the machine's own recogniser was tried. Everything below was run, not read.

**It works, and it is good.** `SFSpeechRecognizer` with
`requiresOnDeviceRecognition: True` needs no network and no model download, and on
this machine `supportsOnDeviceRecognition()` is true and authorization is already
granted. Fed a 3.4-second clip as a live stream of 100 ms chunks, it produced fifteen
callbacks in real time:

```
 0.86s  partial 'Hey'
 0.87s  partial 'Hey can'
 3.58s  partial 'Hey can you hear me I wanted to talk about the upload path'
 3.59s  final   'Hey can you hear me I wanted to talk about the upload path'
```

Word-by-word partials as the audio arrives, the final 0.2 s after the last chunk, and
the text exact. Against the current path — 0.55–1.1 s of silence, then 0.32–0.47 s of
batch transcription — that is text nearly a second earlier, and it is available
*while the user is still speaking* rather than only after they stop.

**Two things stop it being a drop-in, and both were found by probing rather than
assumed.**

The first is the run loop. Apple delivers recognition callbacks on the **main thread's
run loop**, and this was confirmed by isolation: the identical session driven from a
worker thread produced zero callbacks in twelve seconds, while the same code pumped on
the main thread produced fifteen. Uvicorn runs an asyncio loop on the main thread and
pumps no run loop at all, so a streaming recogniser cannot simply be added to the
server as it stands. Either the server moves off the main thread so the main thread can
pump, or the recogniser lives in a helper process of its own — which is a change to how
the app starts, not a new module.

The second is permission. On-device speech needs
`NSSpeechRecognitionUsageDescription` in the bundle's `Info.plist`, which is not there
today, and it needs the user to grant speech recognition. On an unsigned bundle that is
rebuilt every session, the permission is granted to an identity that keeps changing —
the same problem the keychain already has, where a rebuild looks like a different
application and an earlier item reads as somebody else's.

Neither is a reason not to do it. Both are reasons not to start it in the last hour of
a session and hand over something half-built. The dependency was added, the platform
was verified, and the dependency was removed again so the freeze does not carry a
library nothing uses. When this is built it is a feature with a transport, a lifecycle
and a permission; the numbers above say it is worth building.

## September 25, 2026: The three things AgentCall does better

Reading AgentCall properly turned up three ideas worth taking, and none of them is the
part that looks impressive. They rent a headless browser to sit in someone else's
meeting; the transferable parts are all about what happens in the gaps.

**A message that is taken but not read is now reported.** `codex queue` returning zero
only means the message was handed over — the terminal still has to pick it up, and a
busy or wedged session takes it and does nothing. The app used to wait the full
three-minute turn timeout before saying anything about that. It now waits twenty
seconds for *any* sign of life in the rollout — a turn starting, a tool running, a
token counted — and then says the session took the message but has not started working
on it. AgentCall's protocol does this with `command.ack` and `command.error`; theirs is
a wire protocol and ours is a file, but a command that cannot fail loudly is the same
bug in both.

**A pause is judged by how much was said.** The endpointer used a fixed 0.85 s of
silence, which has to be both long enough not to cut off a breath after "hey" and
short enough not to add dead air to every finished sentence. It cannot be both. It is
now 1.1 s early in an utterance and 0.55 s once more than about a second has been
spoken, so a real sentence reaches the session a third of a second sooner and a short
one is not truncated. AgentCall does this with a timer that restarts on every final
transcript and is cancelled by any partial; TalkToMe transcribes a whole utterance at
once and has no partials, so the same intent is expressed with the one signal there is.

**The agent is told to speak before it works.** This is the one that addresses the
actual complaint. A turn that starts silently is a minute or more of the user
wondering whether they were heard, and they fill it by saying "hello?" — which
interrupts the work. The skill now opens with that instruction rather than burying it
as a caveat under "do not narrate your process": say one short line, send it, then do
the work. AgentCall's hosted voice layer says "sure, let me check on that" in under a
second while the agent works; TalkToMe has no such layer, so the line has to come from
the agent itself, which is why it is an instruction rather than a feature.

What was not taken: the meeting bot (nothing of it is in the repository, and it is
inseparable from their hosted service), the hosted voice-intelligence split, and their
WebSocket protocol shape. TalkToMe's link — the terminal owns the session, the app
queues into it and reads the rollout — is a different bet, and the research note says
so plainly.

## September 25, 2026: A voice the account cannot use

A call died on its first spoken word with the provider's own message — *"Free users
cannot use library voices via the API"* — after the user had chosen that voice from a
list the app had offered them. The app listed everything the API returned; the API
returns voices the account may not speak with.

Measured against the real free account rather than read from the docs:

| voice | result |
| --- | --- |
| `premade` (Bella) | **200** |
| copied library voice (Veda Sky) | **402** "Free users cannot use library voices via the API." |
| copied library voice (Lauren B) | **402** same |

The field that looks like it should predict this does not. Both refused voices report
`sharing.free_users_allowed: true` and `rate: 1.0`, because that describes the *owner's*
sharing setting rather than the account asking. So the only dependable rule is the one
the API actually enforces: a voice whose `sharing.status` is `copied` or
`copied_disabled` — a library voice added to the account — needs a paid plan.

`/v1/user/subscription` answers that question, and a restricted key without `user_read`
is refused there with 401. Not knowing is therefore normal, and the app treats it as
"not known paid": a library voice is offered only when the plan is positively read as
paid. Hiding a voice from a paid user costs them a menu entry; offering one to a free
user costs them the call, mid-sentence.

The settings screen says how many were held back and why, because a voice that exists
in the account but not in the list otherwise reads as a bug. A saved voice that is no
longer offered stays visible in the select, labelled "Unavailable", instead of leaving
a blank box, and choosing it again says which kind of voice it is rather than the
generic "select a voice from the list".

Against the real account: 21 premade voices offered, 2 library voices withheld.

## September 25, 2026: Where the latency actually is

The complaint was the gap between speaking and the words arriving in the terminal.
Measured on this machine rather than guessed:

| step | cost |
| --- | --- |
| silence before the app decides the turn ended (`audio.js`) | **0.85 s** |
| transcription, `base.en`, a 3.4 s clip | **0.32–0.47 s** |
| transcription, `small`, the same clip | 1.54–1.60 s |
| `codex queue` spawn and delivery | 0.09–0.31 s |

So a spoken sentence reaches the session in roughly **1.3 s** on `base.en`, and the two
large costs are the fixed silence wait and the model choice — `small` is five times
slower for no gain that matters here.

The rest of the perceived delay is not the app: in the transcript that prompted this,
the agent's own replies are one to two minutes apart, which is Codex thinking. The app
speaks each completed agent message as it lands, so it is not holding anything back.
What it does *not* do is say anything before the first one arrives, and that silence is
the part a faster pipeline cannot fix.

Two things from AgentCall's design are worth taking, recorded in
[research/AGENTCALL.md](research/AGENTCALL.md): a turn-taking timer that restarts on
each final transcript and is cancelled by any partial, which is what makes a shorter
silence threshold safe; and a short spoken acknowledgement before the real answer, so
the wait has a sound in it. Both are behaviour changes rather than tuning, so neither is
in this build.

## September 25, 2026: The sandbox blocks writes too

The call failed again, this time with a traceback out of the bundled binary:

```
File "server.py", line 123, in main
File "talktome/inbox.py", line 61, in _write
PermissionError: [Errno 1] Operation not permitted:
  '~/Library/Application Support/talktome/requests/…request.json.tmp'
```

Moving the request out of a socket and into a file was right, and it was not enough.
Codex's sandbox allows a command to write **its workspace and the temporary folder**
and nothing else, so the app's own folder is refused outright. The same mistake twice:
choosing a meeting place without asking what the sandbox permits.

Measured rather than assumed, using Codex's own runner (`codex sandbox
-c 'sandbox_mode="workspace-write"' -- …`):

| place | writable |
| --- | --- |
| the workspace | yes |
| `$TMPDIR` | yes |
| `/tmp` | yes |
| `~/Library/Application Support/talktome` | **no** |

So the request is left in the app's own folder when that works and in
`/tmp/talktome-<uid>/requests` when it does not. The app watches both and answers
beside whichever one the request arrived in, because reading is not restricted and the
answer therefore always gets home. `/tmp` rather than `$TMPDIR`, which is also allowed,
because it is one path both sides agree on without having to agree on anything — and a
rendezvous that needs two processes to have been started with the same environment is
the same class of bug as this one.

The liveness check had the identical defect one layer down. `server_up` asks whether
the app is up by taking the same `flock` the server holds — and it opened the file with
`O_CREAT`, which a sandboxed command may not do, so a running app was reported closed
and `talktome call` refused to start one. It is opened `O_RDONLY` now; `flock` does not
care how the descriptor was opened, and a shared lock is refused by the exclusive one
the server holds.

Verified under the real sandbox, which is the only place any of this is true: the app's
folder probe reads DENIED, and yet `talktome end` returns the full session snapshot and
`talktome call` returns the app's own "That session has no transcript yet" — the request
travelled through `/tmp` and the answer came back. Every previous check of this feature
ran where the sandbox was not.

## September 25, 2026: The app could not find Codex

The call connected, the greeting played, the user spoke three times, and nothing came
back. The app's own state said why, in a field nobody was looking at:

> `"error": "Codex is not installed, so there is no session to join."`

Codex was running in the window behind it. The app is a packaged Electron bundle, so
Finder starts it with launchd's PATH — `/usr/bin:/bin:/usr/sbin:/sbin` — and
`shutil.which("codex")` searched exactly that. Codex lives in `~/.local/bin`. So
`queue_message` raised, before running anything, and `_run` recorded the refusal.

It presented as the worst possible failure: the transcript filled with the user's own
words, which made it look as though they had been delivered, and the session simply
never answered. `room.utterance` appends the user's message before the adapter is
asked to deliver it, so the app's transcript is not evidence that anything arrived.
The rollout file settles it: it ends at `task_complete` — "The call is connected." —
with one `UserMessage` in it, the one the user typed. None of the spoken ones are
there, because none were ever sent.

This is the same trap as the earlier "nowhere to put the command" defect, in the other
place it was hiding. `agents.find_command` now asks the user's login shell, which is
what `install_command` already does to decide where the `talktome` command can go, and
the three other `shutil.which` calls that look for an agent host use it too. Hits are
remembered, because the answer costs a shell; misses are not, so installing Codex while
the app is open is noticed rather than remembered as absent.

Verified by starting the built binary with `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin`
and asking it: `/v1/managed` reports `{"codex": true, "claude": true}`, where before it
reported both false.

The lesson repeats: the suite ran where `codex` is on PATH. A packaged app does not.

## September 25, 2026: Three bugs behind one port message

`talktome call` reported `Port 8765 is already in use` while a server was demonstrably
listening on 8765 — the app the user had open the whole time. Chasing that produced
three separate faults, and the one that actually printed the message was not the one
either of us expected.

**The installed command was never the command.** The app writes a shim into
`~/.local/bin` that reads `exec "<resources>/talktome-server/talktome-server" -m
talktome "$@"`. That binary is a PyInstaller bundle of `packaging/server.py`, which
ignored `-m talktome` and ran `main()` — so `talktome call` **started a second
server**. On 8765, with the app already holding it, uvicorn said "address already in
use". No call was ever attempted. Nothing could see this: every test ran the command
from the checkout, where `talktome` is a real console script and `-m` means what it
says. Reproduced by running the frozen binary exactly as the shim does, watching it
print `Uvicorn running on http://127.0.0.1:8796` and sit there.

Worse, `talktome.cli` was not in the freeze at all: nothing the server imports reaches
it, so PyInstaller left it out. The binary now honours `-m <module>` the way an
interpreter does — which means the shim did not have to change, and an already
installed one starts working — `talktome.cli` and `talktome.__main__` are collected
explicitly, `--selftest` reports whether the command is present, and `build-app.sh`
fails the build if the frozen binary cannot answer `-m talktome connection`.

**The way in was a socket, and a sandbox has none.** Even with a working command, the
request went over the loopback interface, and Codex runs commands in a sandbox that
blocks it — so the command concluded the app was closed, started a second copy, and
the second copy reported the port. It is now a file: `talktome call` writes a request
into the app's own data folder and the app watches that folder, answering beside it.
Nothing is opened, so there is nothing to block. The request is written *before* the
app is started, because the app reads its inbox as it comes up — a command that wakes
a sleeping app no longer races a health check it could not pass anyway.

**Whether the app is up was a network question.** `config.announce_server()` now takes
an `flock` for as long as the server is listening and `server_up()` reads it. The
kernel drops the lock when the process dies, so unlike a recorded process id it cannot
go stale and cannot be inherited by a process that reuses the number. `wake()` asks
that before it asks the network, so a live server is never started twice.

**The ring's answer moved to the far end.** The app can see whether a ring was taken
and the command cannot, so `ManagedSession.answered()` waits and the reply carries
`"answered"`. That deleted `wait_for_answer`, `_post`, and `_get`.

`scripts/attach_call_smoke.py` now takes `TALKTOME_COMMAND`, so the same fifteen
checks can be pointed at a built bundle instead of the checkout. Against the binary
that ships in the DMG it is 12/12, including `talktome call` and `talktome end` over
the file channel with a real Codex session. That is the packaged-install test
[CONTEXT.md](CONTEXT.md) said did not exist.

## September 25, 2026: A sandboxed agent cannot reach the app

The transcript settled it: `talktome call` **started the app** — the server logs are
right there — and then could not make the request. Codex runs commands inside a
sandbox, and that sandbox blocks the loopback connection the command needs. The app
was reachable and the agent was not allowed to reach it.

The skill now says so where the command is introduced, and says what to do about it,
because the failure looks exactly like a closed app. The command's own message names
both possibilities rather than only the wrong one:

> TalkToMe is not running, or this command cannot reach it. It needs a connection to
> the app on 127.0.0.1, so if commands here run in a sandbox, run this one with
> network access.

The stale keychain item was removed as well, so the next install can store the key
without waiting for a rebuild to pick up the clear-before-write fix.

## September 25, 2026: The keychain error, named at last

The logged exception gave the answer the user-facing message had been hiding:

```
Can't store password on keychain: (-25244, 'Unknown Error')
```

`-25244` is an invalid attempt to change the owner of a keychain item, and the
keychain held exactly that: a `talktome-elevenlabs` item created by a **previous
build**. Without a stable code signature every build is a different application to
the keychain, so writing over an item an earlier build created is refused. This is
the concrete cost of shipping unsigned, and it will recur on every rebuild until the
app is signed consistently.

`configure` now clears the existing item before writing. The item is this app's own
and is being replaced with the key the user just typed, so removing it first is the
right recovery rather than a workaround. Tests cover both the stale-item path and a
missing item, and the existing test now expects the leading delete.

**And the reason `talktome call` failed, which is unrelated and more important.** The
transcript shows the command *starting a server* — so the launch works — and then the
call not being made. Codex runs commands inside a sandbox, and that sandbox blocks
the loopback HTTP request the command needs. The app is reachable; the agent is not
allowed to reach it. That is a design problem, not a bug, and it needs a decision.

## September 25, 2026: Asking the shell, not the app, and hiding the session card

**The app was reporting the truth about itself and a lie about the machine.** Install
refused with "none of ~/.local/bin, /opt/homebrew/bin, or /usr/local/bin is on PATH",
because it read its own environment — and a GUI-launched app inherits launchd's
`/usr/bin:/bin:/usr/sbin:/sbin`, which contains none of them. The agent that runs the
command has the user's *terminal* PATH, where `~/.local/bin` is present. The app now
asks the login shell (`$SHELL -lic 'echo $PATH'`) for the PATH that matters, because
that is the only thing that can answer where a command will actually be found.

This is the same trap as the earlier one about the interpreter path, in a different
disguise: an environment that happens to be correct for the process doing the asking.

Refusing to install left the user with nothing, so the failure now creates
`~/.local/bin`, names the problem, and gives the one line to add to `~/.zshrc`. A
message that only says no is not actionable.

**The managed-session card is hidden.** "Start an agent session" disappears from the
connection screen: the product is joining a session that already exists, not starting
one. The markup is hidden rather than deleted because `app.js` reads those six
elements when it renders the page, and removing them would throw on load.

## September 25, 2026: What the frozen build can actually do, and one real fix

**The keychain was never broken by freezing.** A self-test was added to the frozen
entry point — `talktome-server --selftest` — which reports the keyring backend, the
framework lookups, and a real write and delete. Run against the built binary:

```
keyring_backend   keyring.backends.macOS.Keyring
find_library      Security, CoreServices, Foundation all resolved
macos_api         imported, Security handle <PyInstallerCDLL ...>
keyring_write     ok
```

So the write works from inside the frozen server, and the earlier failure had
another cause that the discarded exception was hiding. The self-test exists precisely
because a frozen app differs from a checkout in ways that only appear at runtime, and
inferring them from a message written for a user is guesswork.

**The real defect was the consequence of the failure, not the failure.** Remembering
is a convenience: the key had already been validated by the provider, and then
`configure` raised, so the entire request failed and **the user was left without a
working key because an optional extra could not be stored**. The key now survives a
keychain that refuses, the setting records what actually happened rather than what was
asked for, and the interface says the key is connected for this session but could not
be stored — with the keychain's own words, now that they are kept rather than
discarded.

**The connection screen no longer hides its primary step.** "Let your agent call you"
was nested inside a collapsed disclosure; it is now the first card on the page, and
the disclosure wraps only the older tool path. The earlier attempts failed because the
check used a regular expression to count tags, which also counts tags inside comments
and so reported an imbalance in a file that had none. It is checked with a real parser
now, and by asserting the order of the two elements, which is what the request was
actually about.

Everything above is in the rebuilt image.

## September 25, 2026: What the first packaged run found

Installing from the DMG and using it turned up three defects that no test had. Two
are fixed here; the third is not.

**The skill was not in the bundle, so Install failed.** `skill_source()` resolved the
repository path, `parents[2] / "skills"`, which is correct in a checkout and
meaningless in a frozen app: there is no repository beside it, so the file was simply
absent and Install reported "missing the TalkToMe skill file". The skill is now
bundled into the server and `skill_source()` looks next to the interpreter first,
falling back to the repository. Two tests cover both layouts.

**The keychain failure was undiagnosable.** `keyring.set_password` failing produced
one fixed sentence about the system keychain being unavailable, with the actual
exception discarded. It is worth knowing that keyring raises the *same* exception
class for "no backend is available" as for a locked keychain, and the two need
opposite responses — so the thrown-away reason was the whole of the useful
information. The underlying error is now logged before the message is raised.

The cause is **not yet known**, and it is specific to the frozen build: keyring works
in the development environment, reporting `keyring.backends.macOS.Keyring` with a
working write, read, and delete. The macOS backend catches `from . import api` and
silently marks itself unavailable when it fails, and `api.py` *is* present in the
frozen tree, so the failure is at runtime inside that module — most likely its
`ctypes.util.find_library` call. The next run will say which, in the server log.

**Not done: the connection screen still hides the skill under a disclosure.** It
should be the primary step and always visible. Three attempts at restructuring that
markup left it unbalanced, and my check for that was counting tags with a regex,
which also counts tags inside comments and so reported a problem in a file that did
not have one. Reverted to the committed markup rather than shipping a broken layout;
the change is a small one and wants doing properly with a real parser.

## September 25, 2026: One command to build the disk image

`npm run build:app` used to be a one-line chain with no way to skip the slow part and
no check that what came out could be opened. It is now `packaging/build-app.sh`,
which freezes the server, draws the icon, bundles, and then **mounts the image it
just built** and reports what is inside it. An image that builds and does not open is
the failure worth catching, and it is not visible from a filename or an exit code.

`npm run build:dmg` skips the freeze and takes about a minute less. Freezing is the
slow half, needs no network, and only has to be redone when Python changes.

Both paths were run end to end, not just the fast one: the full build produced a
208 MB image whose app is 508 MB installed, with the frozen server present, the menu
bar flag set, and a checksum to compare against.

## September 25, 2026: A test that wrote into the system, and removing everything

Nothing was left on the machine: Codex, Claude, and DeepSeek Harness registrations,
the skill, and the `talktome` command are all gone, verified through each client's
own tooling rather than by reading files. Backups are in `~/talktome-removed-*`.

Removing the skill and the command needed uninstall paths that did not exist, so
`uninstall_skill` and `uninstall_command` were written first. The command is only
removed if it carries this app's marker: `talktome` is a plausible name for someone
else's tool, and deleting theirs would be worse than leaving ours behind.

**The serious finding: a test had been writing into system directories.** Three
tests called `install_command`, which writes a shell script into the first
directory on PATH. They passed a temporary directory as `home` and monkeypatched
`Path.home`, but `Path.expanduser()` resolves `~` from the environment and not from
a patched `Path.home`, so `"~/.local/bin"` became the real home and
`"/opt/homebrew/bin"` needed no expansion at all. Every test run left a broken
`talktome` in `/opt/homebrew/bin` pointing at `/usr/bin/python3`, which has no
`talktome` package. Nothing failed, because nothing was checking.

Fixed by making it structural instead of remembering: an autouse fixture redirects
`COMMAND_DIRS` and `PATH` for the whole module, so no test can write a command
outside its temporary directory. A regression test asserts the only file written
lands in the sandbox, and the suite was run twice with the stray paths absent both
before and after.

**Two more defects found while removing everything:**

- **A command the app had just installed read as missing.** `command_installed`
  looked for `sys.executable` as text, and the same interpreter is spelled `python`
  or `python3` depending on how it was invoked — the identical mistake already fixed
  once for the agent clients' configuration. It compares resolved paths now.
- **`command_dirs` took a `home` it never used**, which is part of how the tests
  came to resolve real directories. It takes only the PATH now.

## September 25, 2026: A double-clickable app, unsigned

`npm run build:app` now produces `TalkToMe.app`: Electron wrapped around the frozen
server, with the app icon drawn from the same two threads as the call surface.
Verified by launching the bundle and asking it for the interface, not by inspecting
it:

- The bundled server starts on its own and answers `/v1/health`.
- The whole app launches and serves the interface, and computes a launcher of
  `open -g -a "<the bundle>"` for the `talktome` command it installs, so an agent can
  start the packaged app the same way it starts a checkout.

Three things the packaging needed that are not obvious from an electron-builder
config:

- **`LSUIElement`**: menubar only. That is the product decision, and it also means
  the menu bar item is the only way to reach Settings, so it has to stay complete.
- **The server is a binary, not a module.** `main.cjs` spawned
  `<repo>/.venv/bin/python -m talktome serve`, and a bundle has neither. It now starts
  `Resources/talktome-server/talktome-server` and passes the port in the environment,
  because the frozen entry point reads it there while the checkout's command takes it
  as an argument. Both are passed so one spawn call covers either.
- **`cwd` cannot be the checkout.** With no checkout there is no project folder, so a
  packaged app starts in the user's home and lets them pick a folder in the app.

The icon is generated rather than committed: `scripts/make-app-icon.mjs` draws the
pill's material with the threads on it and runs it through `iconutil`. The menu bar
mark stays a separate monochrome template, because a menu bar glyph and a Finder icon
are different problems even when they are the same idea.

**It is unsigned.** electron-builder is configured with `identity: null` and
`hardenedRuntime: false`, which is enough for this machine and not enough for anyone
else's. The certificate situation is worth stating plainly: the machine has an
**Apple Development** certificate, which a free Apple ID can also create, and which
cannot notarize. A **Developer ID Application** certificate is paid-only. The
entitlements work that signing will need — the frozen Python loads native libraries
and JITs, which the hardened runtime blocks — is the same either way, so it can be
done later without redoing the bundle.

**The Electron suites finally ran.** They had been deferred all day because the
running app holds the single-instance lock and the tests launch their own instance.
With it closed: 21 of 21 on the call surface, and the desktop suite passing with no
page errors. 170 Python tests, 57 JavaScript tests, and the attachment smoke at 12 of
12.

## September 24, 2026: The two ring gaps

**Answering was only possible on the pill**, a small target inside a ring that lasts
ten seconds. The menu bar item now offers "Answer call" whenever a ring is pending,
which is also the only other surface that exists: a menubar-only app with no Dock
icon has nowhere else to put it.

**The agent could not tell an unanswered ring from a quiet call.** `talktome call`
returned as soon as it rang, so an agent that had said "I have started a call" had no
way to know whether anyone picked up, and could not say which of the two happened.
The command now waits for the outcome and reports it: `"answered": true` once the
call is taken, `"answered": false` if the ring stopped on its own. `--no-wait` skips
the wait for a caller that intends to answer the ring itself.

This is only tolerable because the ring is ten seconds. A command that blocked for
forty five would be a command agents time out on.

One interaction this created, worth recording because it is the kind of thing that
looks like a flaky test: the attachment smoke test rang with the command and then
answered the ring through the API, but the command was now waiting for that answer,
so by the time it returned the ring had expired. The test was answering on behalf of
the pill, so it uses `--no-wait`, and a second scenario covers the waiting form by
ringing in the background, answering mid-ring, and reading the reported outcome.

## September 24, 2026: An agent can start the app

A closed app was a dead end: `talktome call` printed "TalkToMe is not running" and
stopped. That makes the reach conditional on the user having opened the app first,
which is the wrong way round — they ask their agent to talk, and the app should
appear because of that, not before it.

The app now writes its own start command into the `talktome` command when it
installs it, because only the app knows whether it is a packaged bundle or a
checkout:

- Packaged: `open -g -b <bundle id>`, started without focus, since the ring is what
  asks for attention and not a window appearing over the user's work.
- A checkout: the Electron binary and the repository, which is how it is started
  today.

`cli.wake` runs it detached, so it outlives the command, and waits up to twenty five
seconds for the server to answer before retrying the call once. A user who has never
heard of the command line still gets a call. If no launcher is known it says so
rather than pretending to have tried.

Verified against the frozen server rather than a mock: with nothing listening,
`wake()` returned true in 0.9 seconds and the server was answering afterwards. The
real app is slower than that, which is what the timeout is for.

## September 24, 2026: Proving the server can be frozen, and one required step

**Packaging's risky half is the Python, not Electron.** `desktop/main.cjs` spawns
`<repo>/.venv/bin/python`, and a real `.app` has neither the repo nor a virtual
environment. So before building anything around it, the question was whether
PyInstaller can freeze the server with its native libraries intact. It can:
`packaging/build-server.sh` produces a 200 MB self-contained directory, and both
heavy paths were exercised against the real models rather than assumed.

- **Whisper survives.** Transcribing generated speech through the frozen build
  returned `"Hello, please help me build a local voice application."`, so
  `faster-whisper`, `ctranslate2`, `av`, and `tokenizers` all bundle.
- **Kokoro survives, but only once its data does.** The first build failed with
  `data path not exists at .../_internal/espeakng_loader/espeak-ng-data`: Kokoro's
  tokenizer needs espeak's data directory and PyInstaller does not know to collect
  it. `--collect-all espeakng_loader` fixed it, and the frozen build then reported
  `status: ready` and produced 1.68 seconds of 24 kHz audio.

Two other things the freeze needed, both worth knowing rather than rediscovering:

- **The frontend is not a Python module.** The first frozen build booted and then
  died mounting `StaticFiles`: 200 MB of interpreter and no HTML. `--add-data` puts
  `src/talktome/static` where `Path(__file__).parent / "static"` looks for it in a
  frozen build.
- **`--specpath` changes what relative paths mean.** An `--add-data` path is
  resolved against the spec directory, not the working directory, so it has to be
  absolute.
- **`--collect-all mcp` breaks the build.** It pulls in `mcp.cli`, which imports
  `typer`, which is not a dependency. The server never imports MCP at all: the only
  reference is the `-m talktome.mcp_server` string in the argv it registers with a
  client, so the whole `--collect-all` was unnecessary.

**The connection screen asks for one thing now.** The skill and the `talktome`
command are the only install the current product uses: attachment needs them,
managed sessions need neither, and the MCP tools serve only the older flow where an
agent connects and waits on `talktome_listen()`. `managed.py` and `attach.py` contain
no reference to MCP at all. So the skill is the required step, the readiness check
keys off it rather than off a tool registration, and the three client rows moved
behind an "Older tool connection" disclosure.

## September 24, 2026: Making the command reachable, and one answer on the ring

**The feature was built, verified end to end, and unusable.** The skill's first
instruction is `talktome call --thread "$CODEX_THREAD_ID"`, and `talktome` existed
only inside the app's own virtual environment. No terminal has that on its PATH, so
for any real user the command was not found and nothing happened. Eleven passing
checks and one broken product, which is the failure mode a test suite cannot see:
every check ran inside the environment that had the command, and the user's shell
does not.

The connection screen's skill step now installs both halves, because the skill and
the command are one feature and either alone does nothing. `install_command` writes
a three-line shim into the first of `~/.local/bin`, `/opt/homebrew/bin`, or
`/usr/local/bin` that is actually on PATH, running the same interpreter the app runs
so it cannot drift from it. If none of them is on PATH it says so rather than
writing somewhere the shell will never look, which would look like success.

`skill_status` now reports the two halves separately, so the interface can say
"installed, but the talktome command is not on PATH" instead of a bare "not
installed" with no clue which part is missing. `installed` means an agent can do the
thing, not that a file exists.

**The ring lost its decline button and its window was cut to ten seconds.** Ringing
is now answer or wait: there is no way to dismiss it by hand, so ten seconds is the
whole of the time a user has to notice it, decide, and reach the pill. This was the
user's call over a recommendation to keep a dismiss control and allow about twenty
seconds. A test pins the window to a sane range so it cannot drift silently. The
`decline` path stays on the server, where the ring timeout and `talktome end` still
use it.

## September 24, 2026: Ringing, and hanging up from the terminal

An agent no longer seizes the microphone when it decides to talk. `talktome call`
now **rings**: the pill shows a bell, who is calling, and an answer and a decline,
and the agent's greeting is heard only once the user answers. The terminal can also
end a call with `talktome end`, so hanging up no longer needs someone looking at the
screen.

**Three defects, and the second one is the reason this took a second pass:**

1. **The greeting was never actually spoken.** The speech worker validates each
   utterance against the room's current turn, and a greeting has no turn — it is
   said before the user has spoken. Every greeting was therefore dropped on the way
   to the voice while still appearing in the transcript. The earlier attachment test
   passed because it checked the transcript and not the audio, which is exactly the
   kind of check that looks like proof and is not. There is now a test for the audio.
2. **The ring timer cancelled itself.** Ending an unanswered ring means declining it,
   and declining stops the timer, so the timer cancelled the task it was running in:
   `CancelledError` at the next await, half-torn-down ring, and a session stuck in
   `ringing` forever. It surfaced as a test that hung rather than failed, which cost
   a four-minute timeout to notice.
3. **`hangup` deadlocked the session.** It held the lock and then called `decline`,
   which takes the same non-reentrant lock. Reading what to release under the lock
   and releasing it outside fixed it. Same symptom as above: a hang, not a failure.

**Two decisions were put to the user first**, because "ringing" was my own phrase
and was nowhere in the design record:

- **The classic phone model.** Ring, then wait to be answered. The alternative — ring
  and answer itself — would have been less work and less respectful of the user's
  attention.
- **`talktome end` for anyone, including the agent**, with the skill saying when to
  use it and when not to.

**The ringing surface is its own layout.** Mute and transcript mean nothing before
someone has answered, so ringing shows a different capsule rather than reusing the
call controls. A CSS bug worth recording: `#ringing .icon` was meant for the bell
and also matched the icon spans inside the two buttons, and at equal specificity a
class beats a type, so both handsets were drawn in the dark colour meant for the
bell on its lime circle — two dark glyphs on red and green circles.

**Verification.** `npm run test:attach-call` now proves the whole loop against a real
Codex session: ring, decline nothing, answer, hear the greeting, talk, get an answer
read out of the rollout, and hang up from the terminal — eleven checks. The Electron
suite grew a check for the terminal hangup specifically, because that arrives by a
different route (a server-side hangup the hidden window notices on its next poll)
and assuming it behaved like the button is the kind of assumption this project has
been punished for. 148 Python tests, 57 JavaScript tests, and the desktop and
onboarding suites all pass with ruff clean.

## September 24, 2026: Joining a session that is already running

An agent can now ring the app. The agent runs one command from inside its own
session, the floating pill appears with the agent's own opening line, the user
talks, and the agent answers in the session it was already in — same model, same
tools, same history, same terminal.

**The whole agent-facing surface is one command:**

```sh
talktome call --thread "$CODEX_THREAD_ID" --greeting "Hey — what's up?"
```

`src/talktome/attach.py` holds the machinery. `Rollout` follows a thread's
append-only JSON Lines file by byte offset, which is the only public view of a
thread this process does not own. `AttachedAdapter` wears the managed adapters'
`start`/`run`/`close` interface, so the speech pipeline, the transcript, the
streaming voice, and the call surface are all unchanged: the difference between a
managed call and an attached one is confined to one class.

**The record shapes were read out of real rollout files rather than assumed.**
Agent replies are `event_msg`/`item_completed` with an `AgentMessage` item, carrying
`text` and a `phase`. The same stream carries `Reasoning`, `CommandExecution`, and
`FileChange` — including full command output, which ran to kilobytes in the files
inspected. Only agent messages are spoken, and command work becomes one short
phrase, because reading any of the rest aloud would put private reasoning and
terminal output into the user's ears. Tests pin each of those refusals.

**A real limitation, and it is the opposite of the managed path's rule.** Codex
allows one writer per thread and the terminal holds it, so nothing this app does can
stop a turn in progress. `codex queue` delivers a message into a held thread but has
no interrupt option. The app can stop speaking and that is all: if the user talks
over a long turn, the queued message is answered when the agent gets to it. This is
why the managed path's "interrupt, do not queue" decision cannot be carried across
unchanged, and the interface should eventually say so rather than let the user
wonder why the agent went quiet.

**Three defects, in the order they would have hurt:**

1. **`talktome call` reported failure after succeeding.** The response check used
   `response.ok`, which is `requests`, not `httpx`. The POST had already started the
   call, so the agent would have told the user the call failed while it was live and
   ringing. The test for this uses a real `httpx.Response` rather than a stand-in,
   because a stand-in with an `ok` attribute passes.
2. **An attached call never started a call.** `attach` connected the agent but left
   the room without a call id, so there was nothing to speak into. An agent that
   rings in is a live call already: the user answers by talking, and nothing in the
   window has to be pressed.
3. **The greeting had nowhere to go** for the same reason, since it is spoken
   through the call's audio queue.

**The skill is part of the setup, not an extra.** Installing the tools without it
leaves an agent that can be started from the app but cannot ring in, so the
connection screen lists it beside the agents. An edited skill is offered again
rather than looking installed, because an agent following stale instructions is
worse than one with none.

**Verification.** `npm run test:attach-call` drives the whole loop against a real
Codex session: a real app server holds a real thread, the real `talktome call`
command rings the app, the user's speech travels through `codex queue` into the held
thread, the agent's answer is read out of the rollout file and appears in the
transcript, and the terminal session still works afterwards. Seven checks, all
passing. 134 Python tests including 28 for attachment, 57 JavaScript tests, and the
call, desktop, and onboarding suites all pass with ruff clean.

## September 24, 2026: The pill made small, opaque, and movable

The surface was too large and too see-through to sit over someone's work. The pill
went from 700x86 to 340x56, and the window from 720x110 to 360x76.

**Two defects, both of which looked fine in the code:**

1. **Both microphone glyphs were painted at once.** The muted state swapped a
   `hidden` property, but these are SVG elements, and `hidden` is an IDL property of
   `HTMLElement`, not `SVGElement`. Assigning it set a plain JavaScript property and
   never touched the attribute, so the stylesheet — which selects on the attribute —
   kept drawing both glyphs. Worse, reading the property back returned `true`, so a
   check of the state agreed with the code and not with the screen. The attribute is
   now toggled, and an explicit rule hides a hidden SVG because the browser's own
   `[hidden]` rule is written for HTML elements.
2. **The threads stopped rather than passed through.** The envelope draws them to
   the centre line at both edges, but they then ended there with rounded caps and a
   glow, which read as a deliberate full stop. They now dissolve through a gradient
   across the outer sixteen per cent at each end.

**The controls lost their labels.** At 56 pixels of height a label and a glyph fight
for the same space, and the label was crowding the microphone. The name is carried
by `aria-label` and a tooltip, and each control is a full 44 by 44 target, which is
easier to hit than the labelled version was.

**The material is opaque.** `backdrop-filter` over the user's desktop meant the text
and the threads were being read through whatever was behind them.

**The window is movable, and remembers where it was put.** Dragging anywhere on the
pill that is not a control moves it, through the CSS drag region, so no JavaScript
is involved in the move itself. Opening the transcript then grows the window upward
from the bottom edge the user left, instead of resetting it to the centre of the
display: the anchor keeps the bottom edge and `anchoredBounds` clamps it back on
screen if a display change left it somewhere unreachable. Electron reports every
window move including the ones the application makes itself, so a move matching the
bounds just applied is not mistaken for a drag.

The window is also no longer larger than the pill: it is the pill plus a 10 pixel
ring for the shadow, where it used to leave 24 transparent pixels above the pill.
Every transparent pixel still takes the mouse, so that band was swallowing clicks
meant for the application underneath.

**Verification.** `npm run test:call` grew to twenty checks, covering the window
being exactly the pill plus its ring, the window being movable, and a dragged
position surviving the transcript opening. 96 Python tests, 57 JavaScript tests
including new geometry and thread-gradient coverage, and the desktop and onboarding
suites all pass with ruff clean.

## September 24, 2026: Real audio on the threads

The two threads now follow the real conversation. The user's line is driven by the
microphone, the agent's by its own speech, and the thread that is not speaking
recedes while the other holds the floor.

**Agent playback moved from an `<audio>` element to Web Audio.** This is what makes
the pink thread possible at all: an element gives no way to measure what is coming
out of it. `static/player.js` decodes each reply once and plays it through a
`GainNode` into an `AnalyserNode`, so the surface reads exactly the signal being
heard. `static/app.js` still owns the queue, the turn filtering, and the epoch
cancellation; only the playback mechanism changed.

Scheduling on the audio clock also answers the deferred gapless item. Each chunk is
placed at the previous chunk's end rather than at "now", so consecutive pieces of a
streamed reply are continuous. A chunk hands control back to the queue 120 ms
before its sound ends, which is what lets the next one be scheduled into the
future; without that the queue would only ever start a chunk late. This is
continuous audio rather than a claim of sample accuracy, and it replaces a rebuilt
media pipeline per chunk.

**Levels cross a process boundary.** The surface cannot measure anything itself: the
hidden window owns the microphone and the playback graph. It pushes both levels
about thirty times a second to the main process, which relays them. The numbers are
normalised in one tested place, `normalizeLevel` in `static/threads.js`, rather than
in both the relay and the surface where the two copies could drift apart. A value
that is not a real number reads as silence, because a NaN reaching the canvas would
leave a thread undrawn rather than merely quiet.

The surface also publishes `data-speaker` (`none`, `user`, `agent`, `both`) from its
smoothed levels, which is what makes the whole path observable from outside and
gives CSS a hook for the same state.

**Two defects, both found by running the real thing:**

1. **The voice preview went silent.** It passed a `Blob` to the player, which made
   an object URL and fetched it. The content security policy allows `blob:` for
   `media-src` but not for `connect-src`, so `fetch` failed with "Failed to fetch".
   Rather than widen the policy for a preview, the bytes now go straight to the
   decoder through `playData`.
2. **Agent replies never played at all.** Changing the player to fetch its own URL
   meant the path the queue passed — `/audio/<id>`, relative to `/v1` like every
   other route in that file — was fetched without the prefix and hit the static
   mount. The prefix is added where the player is called.

The second one is worth noting because the first version of the new test did not
catch it: it asserted that a call ends cleanly, which it did. The check that found
it drives a real reply through and waits for the agent thread to move.

**The threads were given motion of their own.** Each one now travels faster while its
own side is speaking — half speed at rest, rising with the level — and the two travel
in opposite directions, so they read as two participants rather than one animation.
Measured on the running surface by capturing a timed frame sequence and correlating
consecutive frames: the user's thread moved about 20 device pixels per 258 ms to the
left while the agent's moved 38 to 79 to the right, both at the same interval. The
phase still wraps, and the wrap point was chosen to be a whole number of periods for
all three sine components in `wave` — 100, 72, and 30 of them — so the loop cannot
produce a jump. A test pins that relationship rather than the number.

Capturing that measurement needed `ui-shot.mjs motion`, which keeps one connection
open and reports the interval it actually achieved. Taking single shots from separate
processes cannot show speed, because the gap between them is dominated by process
start-up: the first attempt looked four times faster than it was.

**Verification.** `npm run test:call` grew two checks: the agent's audio drives the
agent thread, and a measured user level drives the user thread, both through the
real relay. The first drives a real synthesized reply. The second holds a level
rather than sending one, because the application's own timer is reporting silence in
between and a single value is overwritten before it can be observed. 96 Python
tests, 43 JavaScript tests including nine for the player, and the desktop,
onboarding, and call suites all pass with ruff clean. The desktop suite caught the
preview regression, since it previews a voice before it starts a call.

## September 24, 2026: The floating call surface

A live call now takes over the desktop as a floating pill at the bottom centre of
the screen, and the application window steps out of the way. This is the brief's
first milestone: the window, the pill, and the two threads driven by simulated
levels, with real audio deliberately left for the next pass.

**Three decisions were put to the user before any code was written**, because the
brief's assumptions did not all match this codebase:

1. **No React, no build step.** The brief specifies React, Motion, and a
   `src/call-ui/*.tsx` tree. This renderer has no bundler, no TypeScript, and no
   framework: it is plain ES modules served straight off disk, tested with node
   `--test` and Playwright. The pill is built the same way. Canvas was already the
   brief's own choice for the threads, and the six interface transitions it gives
   to Motion are CSS here. A build step would have been the first in this project
   and would have split the frontend into two toolchains.
2. **The main window hides, and a menu bar item brings it back.** Without one,
   Settings would be unreachable for the length of a call.
3. **Agent audio moves to Web Audio later**, which is what will give the pink
   thread a real level and also retire the deferred gapless playback item.

**New in the main process:**

- `desktop/geometry.cjs` holds the pill's bounds as one tested function. It
  derives everything from the display's work area, so a second display with a
  negative origin, a relocated Dock, and a work area too small for the pill all
  come out right. The transcript grows the same window upward while the pill's
  bottom edge stays put.
- The call window is frameless, transparent, always on top at the `floating`
  level, visible on all Spaces, not resizable, and shown with `showInactive()` so
  it never takes focus from whatever the user was typing in. It is 720x110, or
  720x430 with the transcript open. A display change while a call is running
  recomputes the position rather than trusting what was captured at the start.
- `TALKTOME_FLOATING_CALL=0` keeps the call inside the window instead. This
  exists because the desktop test drives the in-window controls and photographs
  that window, which it cannot do while the window is hidden. Without the switch
  that test stalled for thirty seconds on a screenshot of a hidden window. It is
  also a sensible thing for a user to want, and it should become a Settings row.
- A menu bar item, with its icon encoded at runtime by `desktop/png.cjs` and
  `desktop/tray-icon.cjs`. Electron can only build a tray image from a PNG or a
  platform-dependent raw bitmap, so a small PNG encoder lives in the repository
  rather than an image asset or a dependency. Both scales are added as
  representations of one template image, which macOS draws in the menu bar's own
  colour.
- The main window sets `backgroundThrottling: false`. It is hidden for the whole
  call while still owning the microphone, the agent session, and playback, and a
  throttled hidden window would stall all three.

**Architecture:** the hidden window keeps owning the call; the pill is a view and
a remote control. The pill sends `mute` and `end` to the main process, which
forwards them; the hidden window toggles the microphone or ends the call and
reports the new state back. The pill reads the transcript from `/v1/state` using
the session cookie, which the two windows share because they are the same origin.

**Three defects found by testing rather than by reading:**

1. **The threads drew as two straight lines.** `amplitudeFor` returned a fraction
   but `threadY` used it as a pixel count, so a full-amplitude wave moved about
   half a pixel. Amplitude is now a fraction multiplied by the canvas height in
   one place, `swingPixels`, and the tests assert the swing in pixels, because
   that is what a person sees.
2. **The End button rendered transparent.** `#pill button` (one id, one type)
   outranks `#end` (one id), so the red background, the circular radius, and the
   hover colour were all losing. Every End rule now repeats both selectors.
3. **The pill got stuck on "Connecting" after a reload.** Its state arrived in a
   single `did-finish-load` message registered once. The handler is now
   registered for every load. The same pass removed the connecting overlay
   entirely: the brief asks the lines to communicate that state, so a slow dim
   thread does it and the text is reserved for failure.

A fourth was caught by the new desktop test: while the transcript was open, both
the toolbar button and the panel's close button answered to "Close transcript".
The toolbar control is a disclosure toggle, so it now keeps one accessible name
and reports state through `aria-expanded`.

**Verification.** `npm run test:call` drives the real application and inspects the
real windows, because a page screenshot cannot show transparency, always-on-top,
or where macOS actually put the window. Fifteen checks pass: the main window is
hidden during a call, the surface is on screen and always on top, it is 720x110 at
x=540 y=1037 (horizontally centred, 22px above the usable bottom edge), it does
not take focus, the transcript grows the window to 430px without moving the
bottom edge, closing restores the exact bounds, and ending restores the main
window. 96 Python tests, 32 JavaScript tests including the new geometry and thread
math, the desktop and onboarding suites, and ruff all pass.

## September 24, 2026: Removing the connectors, and clause-level speech

**The connectors were removed from Codex and DeepSeek Harness; Claude had none.** The app could
register the MCP server but had no way to take it back, so `agents.py` gained an `uninstall` path
rather than the configs being edited by hand. Codex and Claude are removed through their own `mcp
remove`, and the DSH patch row is deleted while the file's leading comment block survives, leaving
the profile back at its shipped `[]`. A new `POST /v1/agents/{id}/uninstall` reports the new state.

Two defects surfaced while doing it:

1. **The survey misreported Codex as not installed.** `installed` compared the stored interpreter path
   as text, and `sys.executable` ends in `python3` while the stored path ended in `python`. Both name
   one interpreter, so the comparison now resolves the paths. This was not cosmetic: the removal path
   uses the same check to decide whether a registration exists.
2. **Removal had no idempotent case.** `uninstall` now treats an absent registration as already
   correct, so it does not depend on the wording of a client's error. It also refuses clearly when a
   client is gone but its configuration still holds an entry, naming the file to edit.

Before removal the three configs were copied to `~/talktome-connector-backup-20260924-104607`. The
Codex diff shows only the eight lines of the `talktome` block were removed, and the four unrelated
servers (`codex_app`, `computer-use`, `cua_repl`, `node_repl`) are untouched. Verified afterwards
with `codex mcp list`, `claude mcp list`, and by reading the DSH patch file. Session logs and the
ChatGPT-project mirror still mention talktome; those are history, not registrations, and were left.

**Clause-level chunking for local engines was started in the same pass.** A local engine cannot be
handed partial text, so chunk size is the only lever on how soon the first sound arrives.
`SentenceBuffer.feed` takes `clauses=True`, which cuts the turn's *first* chunk at a comma, semicolon,
colon, or em dash — but only at or after 24 characters, and never in preference to a sentence end.
The buffer then stops cutting at clauses, so the extra synthesis request is paid once per turn rather
than per clause. A streaming provider is not cut at clauses at all, because it does its own chunking.

One correction during testing: `first_spoken` in `_run` could not bound this, because a reply that
arrives in a single `message.done` is chunked by one `feed` call, so every chunk in that call took
the clause path. The limit belongs to the buffer, which now owns an `opened` flag.

96 Python tests, 10 JS tests, ruff clean.

## September 24, 2026: Streaming speech and interrupt-first

Speech now starts while the agent is still writing, instead of waiting for a finished reply.

**Interrupt-first was already true for managed turns, so it was verified rather than built.**
`CodexAdapter.run` calls `turn/interrupt` in a `finally` when its consumer is cancelled, and
`test_codex_cancellation_interrupts_the_turn` asserts the exact ids on the wire. Four sibling tests
cover cancellation during start, cancellation with a pending approval, a superseded turn keeping its
thread, and late audio being dropped. Claude cancels by closing its SDK transport. The new work
extends that contract to the socket: a cancelled turn reaches `ElevenLabsStream.abort`.

**New module: `src/talktome/streaming.py`.** `ElevenLabsStream` drives the provider's WebSocket
endpoint, `WordBuffer` holds text to the last word boundary, and `pcm_to_wav` wraps the headerless
frames. `Speech.open_stream` returns a stream only for the ElevenLabs provider with a key present, so
Kokoro and system speech are untouched. `ManagedSession` prefers the stream and falls back to
sentence synthesis when `start()` raises.

Three things were measured rather than assumed:

1. **The protocol is right.** A probe against the live endpoint with a deliberately invalid key
   returned `1008 Invalid API key` — a policy rejection, not a 404. That confirms the URL, the
   `xi-api-key` header through `websockets` 15, and `output_format=pcm_24000` are all accepted.
2. **Text must end at a word boundary.** ElevenLabs reads the trailing space as the cue, so sending
   raw deltas corrupts words. `WordBuffer` was added for this. While testing it, `SentenceBuffer` was
   found to strip whitespace, which would have stalled every push until the next one arrived — the
   managed path now puts the boundary back before pushing, and a test pins that.
3. **A dead socket must not kill the turn.** The first version recorded the error and said nothing,
   so a bad key produced a silent transcript with no audio and no explanation. The turn now reports
   `The streaming voice stopped. <provider reason> The text is in the transcript.`, and an
   intentional abort is not recorded as a failure.

The first-chunk ladder was lowered from the provider default of `[120, 160, 250, 290]` to
`[50, 90, 150, 220]`, and the managed path releases cleaned text at 120 characters rather than only
at sentence ends — always at a space, so markup is never split in half.

`tests/test_streaming.py` covers WAV wrapping, word boundaries, chunk delivery, flush, abort, the
over-long-turn guard, a mid-turn socket failure, and the reason extraction. `tests/test_managed.py`
adds four tests for the stream replacing sentence synthesis, an interrupt aborting the stream, a
stream that will not start falling back, and the reported failure. `tests/test_voice_providers.py`
covers the provider and key gating. 79 Python tests, 10 JS tests, ruff clean.

Still deferred: clause-level chunking for local engines, and gapless playback between chunks.

## September 24, 2026: Managed Codex and Claude sessions

The app now starts Codex App Server or the Claude Agent SDK from its connection page.
Public output enters the transcript before speech completes. An ordered queue plays sentence-level audio without repeated completed messages.
The controller keeps host context across turns and handles supported tool approvals, turn cancellation, and stale audio.
The earlier external MCP and bridge paths remain available under expandable connection controls.

Luna tested the adapters and playback queue with mocked hosts.
The live Codex test used `gpt-6-luna` and passed two turns, context recall, a fixture read, and four audio downloads.
The live Claude test used `haiku` but stopped because its OAuth session expired and could not refresh.
A browser test connected Codex, displayed a reply, and fetched audio without browser errors.
These tests used temporary project and application data. They did not change the user's saved speech settings.

The managed-session guide (since removed) contains setup, permissions, test commands, and remaining limits.
The numbered sections below describe earlier work. Their unfinished adapter proposal now has this initial implementation.

What changed in the interface and the agent integration, why each change was made, and how it was
verified. Written for whoever picks this up next.

Every claim here was checked against the running app, the test suites, or a measurement recorded in
the relevant section. Where something is unfinished, it says so.

---

## 1. Where the product landed

The app was a single conversation view with no navigation, where four screens swapped in place and
setup borrowed the settings layout. It is now a **shell and workspace** application:

- A persistent sidebar holds the conversation list, `New conversation`, `Settings`, and the agent.
- The conversation has one layout for idle and running; only the content area changes.
- Setup is a full-window flow that does not scroll.
- The app registers itself with the agent clients installed on the machine.

The visual language was replaced wholesale: warm paper, cobalt for structure, vermillion for voice,
a system serif for display type, and a static film grain.

---

## 2. Visual system

### Palette

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| Paper | `#f5f2ec` | `#14161a` | window background |
| Sidebar | `#efeae1` | `#191c21` | shell panel |
| Surface | `#ffffff` | `#1e2227` | call bar, composer, cards |
| Cobalt | `#1e4f92` | `#7aa5e8` | structure, primary action |
| Vermillion | `#cc5833` | `#e07a55` | voice, recording, ending a call |
| Muted | `#5f6a78` | `#9aa4b2` | secondary text (4.9:1 on paper) |

`--on-cobalt` (`#fff` light, `#0f151d` dark) exists so filled buttons stay readable in both themes;
`--vermillion-strong` is a darker vermillion for filled destructive buttons, because the accent
vermillion is not dark enough behind white text in dark mode.

Secondary text moved from 3.77:1 to 4.9:1 on the paper background, and `--placeholder` from 2.86:1
to 4.54:1, both to clear the 4.5:1 floor for the 11–12px text they carry.

### Type

Display type is the system serif (`ui-serif`, New York on macOS), shared with the wordmark: page
headings, card headings, the conversation title, the empty-state heading and tagline.
Body copy, labels, buttons, and the compact call-bar status line stay sans — a serif status
indicator reads as decoration; a serif heading reads as structure.

### Grain

A static film grain sits in the background stack of the root element. Measured effect on a flat
region, in the real app:

| Theme | Without | With |
| --- | --- | --- |
| Light | mean 248.57, range 0 | mean 246.59, range 6, std 0.74 |
| Dark | mean 26.72, range 0 | mean 27.12, range 2, std 0.49 |

See [research/BACKGROUND_TEXTURE.md](research/BACKGROUND_TEXTURE.md) for the Arc and Zen comparison
and the parameter reasoning.

---

## 3. The shell

`desktop/preload.cjs` is unchanged in shape; the renderer now renders a sidebar next to a workspace.

- Sidebar is 248px: mark and wordmark right-aligned in the 52px drag strip, a solid cobalt
  `New conversation`, the conversation list, then `Settings` and the agent chip.
- The centred window title is gone. It was a third alignment system competing with the sidebar and
  the page heading.
- The workspace has its own 48px drag strip.

The conversation list renders the **current** conversation only. The library is not built, and the
list says so rather than inventing history.

---

## 4. The conversation screen

Idle and running share one component in one slot:

- **Before a call** the call bar is a hero: 56px waveform, serif `Ready to talk.`, one line of
  context, and one button.
- **During a call** it is a compact bar: 44px waveform, vermillion live dot, status, timer,
  interrupt, and `End conversation`.

The appearance of the call bar is the only layout change, and it happens when a call starts.

The **microphone moved into the composer** as a filled vermillion circle. This reversed an earlier
decision: the microphone now lives with the text input, and the call bar keeps only interrupt and
end. Five competing microphone affordances became one.

**Typing starts the conversation** without switching the microphone on. The microphone button stays
the explicit way to start listening.

**A conversation cannot start without a connected agent.** The hero button becomes
`Connect an agent` and opens the connection screen; the composer explains it instead of silently
failing.

### Empty state

The block is centred between the workspace head and the composer with a slight upward bias, so the
surplus reads as one margin above and one below rather than a void under the content. Suggestions
are hidden until an agent is connected, because they would otherwise be dead controls.

---

## 5. Onboarding

Setup takes the whole window: the sidebar is hidden, the column is centred at 880px, and the footer
actions are pinned to the bottom of the viewport. Neither step scrolls.

- **Step 1** is speech setup.
- **Step 2** is the agent: install, then ask the agent to join.

The manual MCP route lives behind `Add it by hand instead`, folded by default in setup and in normal
use.

**Installing unlocks the next step.** Setup should not trap someone whose agent is not running yet,
so `Open conversation` enables once an agent is installed *or* connected. The footer still says what
the next action is:

| Situation | Footer |
| --- | --- |
| Nothing installed | `Install TalkToMe for an agent to continue.` |
| Installed, not connected | `Open a new agent session and paste the instruction above.` |
| Connected | `<agent name> is connected.` |

---

## 6. Agent integration

`src/talktome/agents.py` registers the MCP server with the clients on the machine. Registration runs
through each client's own mechanism, so every client keeps its own format:

```sh
codex  mcp add talktome --env TALKTOME_URL=… --env TALKTOME_DATA_DIR=… -- <python> -m talktome.mcp_server
claude mcp add talktome -s user -e TALKTOME_URL=… -e TALKTOME_DATA_DIR=… -- <python> -m talktome.mcp_server
```

DeepSeek Harness has no `mcp add`, so the app appends a patch-layer row to
`~/.dsh/profiles/web/cordis.patch.yml`:

```yaml
- insert:
    - id: talktome-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: talktome
        transport: stdio
        command: <python>
        args: ['-m', 'talktome.mcp_server']
```

Both mechanisms were verified before being written down: the CLIs in a throwaway `HOME`, and the DSH
row by composing it with `dsh --profile web --dump-config --patch <temp file>` so a real profile was
never touched. The MCP client ships inside the dsh installation, so no package install is needed.

The installer preserves the DSH file's header comment, keeps unrelated patch entries, and replaces
its own row on reinstall instead of duplicating it.

Endpoints: `GET /v1/agents`, `POST /v1/agents/{id}/install`.

---

## 7. Defects found and fixed

Each of these was reproduced before it was fixed.

### The empty conversation was pinned to the top

`.transcript-panel` had `flex: 1`, so it swallowed the surplus height and pushed the hero up under
the workspace head. Measured before: hero at 86–343, composer at 726 — **240px of dead space**
below. The hero looked centred only because it had a 44px top padding. Fixed with auto margins; the
gap is now 149 above and 199 below.

### The grain did nothing

The first implementation used `body::after` with `mix-blend-mode: overlay`. That measured
**pixel-identical to no grain** on the flat background while still perturbing dark content: `overlay`
screens or multiplies against the backdrop, so on a near-white or near-black surface the output
collapses into a narrow band. Rewritten as a background stack with the strength in the tile's alpha
(`feFuncA slope`), and verified by pixel measurement.

### `/v1/v1/conversation/clear`

`api()` already prepends `/v1`, so the clear button requested `/v1/v1/conversation/clear`. No route
matched, the request fell through to the `StaticFiles` mount, and the server answered
`405 Method Not Allowed`. Fixed, with a static test that rejects any already-prefixed path.

### Speech onset cancelled the pending turn

The microphone raises `onRecording(true)` when **one 2048-sample buffer** crosses the RMS threshold —
about 43ms at 48kHz — but an utterance needs 0.22s of voiced audio. The renderer treated that onset
as "the user is speaking again" and called `/call/interrupt`, which cleared `turn_id` and made the
agent's reply come back as a stale-turn error.

A real session showed it: `agent.interrupted` fired **0.774s** and **1.245s** after each utterance,
from the app, not from the user. The microphone is also paused during playback, so the signal could
never arrive during a reply — it could only ever do harm. Removed; only the interrupt control
invalidates a turn now.

### Dark mode buttons were unreadable

White text on the light cobalt used in dark mode is about **2:1**. Fixed with `--on-cobalt` and a
separate darker vermillion for filled buttons.

### The close button was off-centre

The layout was perfect — button and text box both centred at zero offset — but the `×` glyph's **ink
sat 2 CSS px low**, because a text glyph is positioned by font metrics, not geometry. Replaced with
an SVG cross; measured ink offset went from `dy: +4` device px to `0`.

### Onboarding step 2 overflowed, and the test could not see it

Adding the install card pushed the step to 1015px in an 820px window, so `Open conversation` sat
below the fold. The test asserted `documentElement.scrollHeight <= innerHeight`, but the page scrolls
**internally**, so the document never scrolls and the assertion passed while content was clipped.
Now the test asserts the connect step itself fits, and that the manual route starts folded.

### The copied prompt carried the markup's indentation

The prompt lived in the HTML wrapped across lines, so `textContent` — which the copy button read —
returned the source newlines and leading spaces. CSS collapses that when it *renders*; it does not
when it is copied. The prompt is now a single JS constant that both fills the blockquote and backs
the copy.

### ElevenLabs rejections were opaque

`configure()` validates by calling `GET /v2/voices`, which needs the `voices_read` permission, and
every 401 became "ElevenLabs rejected the API key." A valid key scoped only to speech services is
rejected that way. The app now appends **ElevenLabs' own explanation**, sanitised so the key itself
can never appear in an error string. It still requires `voices_read` to store a key at all, which
remains a false-rejection risk for recognition-only setups.

---

## 8. Tests and tooling

Python tests went from 22 to **39**. Node tests from 3 to **6**.

New guards:

- **Agents** (16 tests): each client's argv, detection from each config format, damaged
  configuration, failed installs, and the DSH patch file — header preservation, replacing rather
  than duplicating, keeping unrelated entries, refusing a non-list file.
- **Frontend** (2 tests): no already-prefixed API path, and `/call/interrupt` posted from exactly one
  place.
- **Microphone** (1 test): a brief noise onset raises the recording signal without producing an
  utterance, documenting why onset must not be treated as a message.
- **Onboarding**: the connect step fits the window, and the manual route starts folded.
- **Desktop**: `turn_survives_microphone` counts `agent.interrupted` across a whole run and asserts
  exactly one, the deliberate click.

### `scripts/ui-shot.mjs`

Drives the running window over its debug port and captures any state:

```sh
node scripts/ui-shot.mjs live <name>            # screenshot the live app
node scripts/ui-shot.mjs eval '<expression>'    # inspect the live DOM
node scripts/ui-shot.mjs states [name ...]      # render scenarios to artifacts/ui
node scripts/ui-shot.mjs sample <x> <y> <w> <h> # ink bounds of a region
node scripts/ui-shot.mjs list
```

`states` mocks `/v1` for the duration and restores the app on exit. `sample` reports the ink
bounding box and its offset from the region centre, which is how the off-centre close button was
measured rather than eyeballed.

### `npm run reset`

Clears saved settings and setup progress so first-run setup can be tested again. Keeps the downloaded
models and the local token, backs up what it removes, refuses to run while the app is open (Electron
rewrites storage on exit and would undo it), and does nothing when there is nothing to clear.

### `TALKTOME_RELOAD=1`

Restarts the local server when a Python file changes, so a backend edit does not need a full app
restart. Frontend edits still only need a window reload.

---

## 9. Documentation added

| File | Contents |
| --- | --- |
| [SCREENS.md](SCREENS.md) | Every screen, every element, every piece of copy, and the visual language |
| [research/EMPTY_STATE_LAYOUT.md](research/EMPTY_STATE_LAYOUT.md) | Layout rules from Apple, Material, NN/g, Gestalt, Fitts, WCAG |
| [research/BACKGROUND_TEXTURE.md](research/BACKGROUND_TEXTURE.md) | How Arc and Zen handle background and grain, and the measured recipe |
| [AGENT_API.md](../AGENT_API.md) | Added the two agent-install endpoints |
| [../README.md](../../README.md) | `TALKTOME_RELOAD`, and how to run setup again |

The layout research also recorded measurements it surfaced but that are not yet acted on: transcript
lines ran to roughly 98 characters at 14px, over the 80-character cap, and the composer's 1px border
is 1.19:1 against the page.

---

## 10. Not done

Ordered by how much they block the product direction.

1. **Agent profiles and the pull adapter.** The agreed direction: the app launches the agent for a
   turn and reads its reply, rather than waiting for an agent to connect and hold a turn open. This
   removes the whole listen-loop failure class. Blocked on deciding session continuity per client.
2. **Conversation library.** Persistence, grouping by date, resume, delete. The sidebar has the slot
   and the empty list message is honest about it.
3. **Working folder picker.** A step in `New conversation`, using Electron's native
   `dialog.showOpenDialog`, stored per conversation. Codex refuses to run outside a git repository,
   so the picker needs to check for `.git`.
4. **Settings restructure.** Settings still uses the old two-card layout, now inside the shell. The
   plan: `General / Voice / Agent / Shortcuts / Advanced` navigation, rows rather than cards, a
   `recommended` badge on Whisper Small, and ElevenLabs collapsed under its provider.
5. **Transcript tool rows.** `Reading src/auth/…`, `Editing 3 files`, `Running tests…` need a new
   agent event, because the protocol cannot report tool activity today.
6. **A talk shortcut.** The reference shows `⌘Space`, which macOS reserves for Spotlight. It needs a
   different binding and must be opt-in.
7. **ElevenLabs permission-aware validation.** Keep a key that works for the selected services and
   only require `voices_read` when a voice list is actually needed.
8. **Screen capture and drawing overlays**, the longer-term direction.
