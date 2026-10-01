cask "talktome" do
  version "0.2.0"
  # The release job summary gives this value for each tag.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/rohanprichard/talktome/releases/download/v#{version}/talktome-#{version}-arm64.dmg"
  name "talktome"
  desc "Voice calls with your coding agents, on this Mac and over SSH"
  homepage "https://github.com/rohanprichard/talktome"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: :sonoma

  app "talktome.app"

  uninstall quit: "com.rohanprichard.talktome"

  zap trash: [
    "~/Library/Application Support/talktome",
    "~/Library/Application Support/talktome-server",
    "~/Library/Preferences/com.rohanprichard.talktome.plist",
    "~/Library/Saved Application State/com.rohanprichard.talktome.savedState",
  ]

  caveats <<~EOS
    talktome is not notarized yet, so macOS blocks the first start.
    To open it, do one of these:
      1. Open talktome once. Then select System Settings > Privacy & Security > Open Anyway.
      2. Run: xattr -dr com.apple.quarantine "#{appdir}/talktome.app"
  EOS
end
