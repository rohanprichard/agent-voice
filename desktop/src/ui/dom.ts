// Small helpers the windows share. This file is a plain script, loaded before
// each window's own script.

function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {}, ...children: Array<Node | string>): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "text") node.textContent = value;
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

function button(label: string, className: string, onClick: () => void): HTMLButtonElement {
  const node = el("button", { class: className, type: "button", text: label });
  node.addEventListener("click", onClick);
  return node;
}

function followTheme(): void {
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => (document.documentElement.dataset.theme = dark.matches ? "dark" : "light");
  apply();
  dark.addEventListener("change", apply);
}
