const select = document.getElementById("call-transcripts");
const status = document.getElementById("call-transcripts-status");

document.getElementById("open-calls").addEventListener("click", () => {
  window.talktomeDesktop?.openCalls?.()?.catch?.(() => {});
});

// The main window signs in after this script loads, so the first reads can be
// refused until then.
async function load(attempt = 0) {
  const response = await fetch("/v1/calls").catch(() => null);
  if (!response?.ok) {
    if (attempt < 30) setTimeout(() => void load(attempt + 1), 1000);
    return;
  }
  select.value = (await response.json()).transcripts;
}

select.addEventListener("change", async () => {
  status.textContent = "";
  const response = await fetch("/v1/calls/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcripts: select.value }),
  }).catch(() => null);
  if (!response?.ok) {
    status.textContent = "The setting did not save. Try again.";
    void load();
  }
});

void load();
