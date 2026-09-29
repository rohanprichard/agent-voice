cask "talktome" do
  version "0.1.0"
  # The release job summary gives this value for each tag.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/rohanprichard/talktome/releases/download/v#{version}/TalkToMe-#{version}-arm64.dmg"
  name "TalkToMe"
  desc "Voice calls with the coding agent you already use"
  homepage "https://github.com/rohanprichard/talktome"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: :sonoma

  app "TalkToMe.app"

  uninstall quit: "com.rohanprichard.talktome"

  zap trash: [
    "~/Library/Application Support/talktome",
    "~/Library/Caches/talktome-server",
    "~/Library/HTTPStorages/talktome-server",
    "~/Library/Logs/TalkToMe",
    "~/Library/Preferences/com.rohanprichard.talktome.plist",
    "~/Library/Saved Application State/com.rohanprichard.talktome.savedState",
  ]

  caveats <<~EOS
    TalkToMe is not notarized yet, so macOS blocks the first start.
    To open it, do one of these:
      1. Open TalkToMe once. Then select System Settings > Privacy & Security > Open Anyway.
      2. Run: xattr -dr com.apple.quarantine "#{appdir}/TalkToMe.app"
  EOS
end
