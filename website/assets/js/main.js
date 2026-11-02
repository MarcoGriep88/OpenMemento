// The examples are illustrative; no media, analytics or API requests are made.
const exampleButtons = document.querySelectorAll('[data-example]');
const examplePanels = document.querySelectorAll('[data-panel]');
exampleButtons.forEach((button) => {
  button.addEventListener('click', () => {
    exampleButtons.forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
    examplePanels.forEach((panel) => { panel.hidden = panel.dataset.panel !== button.dataset.example; });
  });
});
