#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
preview="dist/previews/TalkToMe Notch Preview.app"
mkdir -p "$preview/Contents/MacOS"
xcrun swiftc -O native/NotchGlow.swift -o "$preview/Contents/MacOS/NotchGlowProbe"
cat > "$preview/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.rohanprichard.talktome.notchpreview</string>
<key>CFBundleName</key><string>TalkToMe Notch Preview</string>
<key>CFBundleExecutable</key><string>NotchGlowProbe</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
printf '%s\n' "$preview"
