(() => {
  // Dark is the default. System and Light are choices in Settings.
  const DEFAULT = "dark";
  const valid = (value) => (["system", "light", "dark"].includes(value) ? value : DEFAULT);
  let preference = DEFAULT;
  try {
    preference = valid(localStorage.getItem("talktome-theme"));
  } catch {}
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  function apply() {
    document.documentElement.dataset.theme =
      preference === "system"
        ? system.matches
          ? "dark"
          : "light"
        : preference;
    document.documentElement.dataset.themePreference = preference;
    // Only the Settings window has this bridge. It keeps the window background
    // and the other windows on the same theme.
    window.talktomeDesktop?.setTheme?.(preference)?.catch?.(() => {});
  }
  window.setTalktomeTheme = (next) => {
    preference = valid(next);
    localStorage.setItem("talktome-theme", preference);
    apply();
  };
  system.addEventListener("change", apply);
  // A change in Settings reaches the onboarding window and the call surface too.
  window.addEventListener("storage", (event) => {
    if (event.key !== "talktome-theme") return;
    preference = valid(event.newValue);
    apply();
  });
  apply();
})();
