const toggle = document.querySelector<HTMLButtonElement>(".debug-toggle");
const label = document.querySelector<HTMLElement>(".debug-toggle__label");

toggle?.addEventListener("click", () => {
  const enabled = document.body.dataset.debug !== "true";
  document.body.dataset.debug = String(enabled);
  toggle.setAttribute("aria-pressed", String(enabled));
  if (label) label.textContent = enabled ? "Hide geometry" : "Show geometry";
});

document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "g" && !(event.target instanceof HTMLElement && event.target.isContentEditable)) {
    toggle?.click();
  }
});
