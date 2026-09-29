#!/bin/sh
# Build TalkToMe.app and a disk image you can install from.
#
#   sh packaging/build-app.sh                everything
#   sh packaging/build-app.sh --skip-server  reuse the last frozen server
#
# The awkward half is the Python. A bundle has no virtual environment and no
# checkout, so the server is frozen into a binary first and copied in. Freezing takes
# about a minute, needs no network, and only has to be redone when Python changes,
# which is what --skip-server is for.
#
# The result has an ad-hoc signature, not a Developer ID. It opens on this machine
# without a prompt, because a locally built image is never quarantined. A download
# is quarantined, so another Mac opens it only after Privacy & Security > Open Anyway.
set -e
cd "$(dirname "$0")/.."

SKIP_SERVER=0
for argument in "$@"; do
  [ "$argument" = "--skip-server" ] && SKIP_SERVER=1
done

if [ "$SKIP_SERVER" -eq 1 ]; then
  if [ ! -x dist/frozen/talktome-server/talktome-server ]; then
    echo "Nothing frozen to reuse yet. Run again without --skip-server." >&2
    exit 1
  fi
  echo "==> reusing the frozen server"
else
  echo "==> freezing the server"
  sh packaging/build-server.sh
fi

# The binary is two programs, and only one of them is the server. The command an
# agent runs is the other, and it is easy to lose: nothing the server imports
# reaches `talktome.cli`, so the first bundle left it out and `talktome call` started
# a second server on the port the app already held. No test in the checkout can see
# that, because they all run the command from the checkout. So it is asked here.
echo "==> checking the frozen binary can still be the talktome command"
COMMAND="$PWD/dist/frozen/talktome-server/talktome-server"
PROBE=$(mktemp -d)
if ! TALKTOME_DATA_DIR="$PROBE" "$COMMAND" -m talktome connection | grep -q '"url"'; then
  echo "The frozen binary cannot run the talktome command: an agent's call would" >&2
  echo "start a second server instead. Check packaging/build-server.sh." >&2
  rm -rf "$PROBE"
  exit 1
fi
if ! TALKTOME_DATA_DIR="$PROBE" "$COMMAND" --selftest | grep -q '"command": "ok"'; then
  echo "The frozen binary's own self-test does not report a working command." >&2
  rm -rf "$PROBE"
  exit 1
fi
rm -rf "$PROBE"

echo "==> drawing the TalkToMe app icon"
node scripts/make-app-icon.mjs

echo "==> building the native notch glow"
NOTCH_APP=dist/native/NotchSurface.app
mkdir -p "$NOTCH_APP/Contents/MacOS"
# swiftc targets this Mac's macOS by default, and then the helper does not start on
# an older one. Keep this the same as minimumSystemVersion in package.json.
xcrun swiftc -O -target arm64-apple-macos14.0 native/NotchGlow.swift -o "$NOTCH_APP/Contents/MacOS/NotchSurface"
VERSION=$(node -p "require('./package.json').version")
cat > "$NOTCH_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>NotchSurface</string>
  <key>CFBundleIdentifier</key><string>com.rohanprichard.talktome.notch</string>
  <key>CFBundleName</key><string>TalkToMe Notch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

echo "==> building the bundle and the disk image"
npx electron-builder --mac --publish never

# Verified by mounting rather than by trusting the filenames: a disk image that
# builds and does not open is the failure this catches.
DMG=$(ls -t dist/app/*.dmg | head -1)
VOLUME=/tmp/talktome-verify-$$
hdiutil attach "$DMG" -nobrowse -quiet -mountpoint "$VOLUME"
APP=$(ls -d "$VOLUME"/*.app | head -1)
NAME=$(basename "$APP" .app)
INSTALLED=$(du -sh "$APP" | cut -f1)
SERVER=$([ -x "$APP/Contents/Resources/talktome-server/talktome-server" ] && echo yes || echo MISSING)
MENUBAR=$(/usr/libexec/PlistBuddy -c "Print :LSUIElement" "$APP/Contents/Info.plist" 2>/dev/null || echo missing)
SIGNED=$(codesign --verify --deep --strict "$APP" 2>&1 && echo "ad-hoc, valid" || echo INVALID)
hdiutil detach "$VOLUME" -quiet

printf '\n%s\n' "$DMG"
printf '  app          %s, %s installed\n' "$NAME" "$INSTALLED"
printf '  server       %s\n' "$SERVER"
printf '  menu bar     %s\n' "$MENUBAR"
printf '  signature    %s\n' "$SIGNED"
printf '  size         %s\n' "$(du -h "$DMG" | cut -f1)"
printf '  zip          %s\n' "$(ls -t dist/app/*.zip | head -1)"
printf '  sha256       %s\n' "$(shasum -a 256 "$DMG" | cut -d' ' -f1)"
printf '  install      open it, drag %s to Applications\n' "$NAME"
