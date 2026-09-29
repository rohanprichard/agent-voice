# TalkToMe Notch Silent Preview

This app shows a native Notch preview. It uses local preview states.

## Use

1. Run `npm run build:notch-preview`.
2. Open `dist/previews/TalkToMe Notch Preview.app` in Finder.

The app opens the preview controls. It also adds the `Notch preview` menu bar item.

Select a state or a glow color in the preview controls. Select a state from the menu bar item.

Select `Show notch` to hide the controls and show the notch surface. Select `Preview controls` in the menu to show them again.

Select `Close preview` in the controls or menu to close the app.

## Preview behavior

The app does not start a call. The app does not use a microphone. The app does not use a network connection.

The call buttons change local preview states. The transcript button opens a detached window with a sample transcript.

The sample transcript has fixed text. It does not show a live call transcript.

## Screen measurement

The current measured safe area is 220 pt wide and 38 pt deep.

The app gets this area from the display safe-area values. It uses the area to place the preview surface.

The shoulder curves use smooth S shapes beside the camera. The horizontal wing line is 0.5 pt below the display top.

The lower edge is 0.5 pt below the safe-area depth. On this Mac, the edge is at 38.5 pt from the screen top.
The previous 27 pt downward extension is removed. Each shoulder starts 65 pt outside the corresponding camera side.
The lower edge spans the measured camera width, plus 0.75 pt at each end.
The glow ends 160 pt beyond each measured camera side. Its outer 95 pt fades to transparent.
Each color preset uses a more saturated color. The curve and downward halo keep their previous geometry.
Only the central shoulder mask has a black fill. The outer wings have no black strip above them.

The call controls use a separate pill at the top center, below the notch glow.
The notch has only the glow. The pill starts 64 pt below the measured camera depth.
The pill uses black at 96% opacity. Its connected state is 280 pt wide and 56 pt high.
The incoming state is 320 pt wide and 64 pt high.
The pill shows the timer on the left and three call buttons on the right.
The thin glow edge uses the glow color without a white mixture.
An additional soft halo sits 6 pt below the glow path. It extends the light downward without moving the bright edge.

The controls use 30 pt buttons, with 42 pt between centers in connected states.
The preview timer measures time since the native surface entered a connected state.
The full app supplies the call start time for its timer.
Drag the pill background or timer to move the controls. The notch glow stays fixed.
Drag the transcript header to move the transcript independently.
The glow follows the camera boundary. The separate pill has no luminous border.

## Visual examination

The native source compiled. Earlier app screenshots showed the corrected Hover and Connected states.
The user will examine the latest screen-edge taper and retained call panel on the physical display.
The user supplied a physical display photo. It showed that the previous curve added an artificial black extension below the camera.
The corrected shoulders stay beside the camera rectangle. The thin core starts below its measured lower edge.
The broad colored stroke is behind the black mask. Only the thin core is above the mask.
No real call ran during these steps.

## Limits

This preview is separate from live calls. The full app uses the same native source.
The user still needs to examine the call controls in the built app.

A screenshot of the app panel cannot establish the physical hardware seam. Examine the seam on the physical display.
