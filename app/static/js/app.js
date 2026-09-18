// Ephemeral toast (success/error/warning), used for one-shot confirmations
// after a redirect so feedback disappears on its own instead of sitting as
// a permanent banner. Exposed on window so any inline page script can call
// it directly (e.g. after a fetch-based action) in addition to the
// flash-query-param flow below.
function showToast(message, category) {
  const container = document.getElementById("toastContainer");
  if (!container || !message) return;

  const toast = document.createElement("div");
  toast.className = "toast align-items-center border-0 text-bg-" + (category || "success");
  toast.setAttribute("role", "alert");
  toast.setAttribute("aria-live", "assertive");
  toast.setAttribute("aria-atomic", "true");
  toast.innerHTML =
    '<div class="d-flex">' +
    '<div class="toast-body"></div>' +
    '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Fermer"></button>' +
    "</div>";
  toast.querySelector(".toast-body").textContent = message;
  container.appendChild(toast);

  const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
  toast.addEventListener("hidden.bs.toast", function () {
    toast.remove();
  });
  bsToast.show();
}
window.showToast = showToast;

// Read the one-shot flash message base.html stamped onto <body data-flash>
// from the redirect's query string, show it, then scrub the query string so
// a refresh doesn't replay it.
document.addEventListener("DOMContentLoaded", function () {
  const flash = document.body.dataset.flash;
  if (!flash) return;
  showToast(flash, document.body.dataset.flashCategory);
  const url = new URL(window.location.href);
  url.searchParams.delete("flash");
  url.searchParams.delete("flash_category");
  window.history.replaceState({}, "", url.pathname + url.search + url.hash);
});

// Confirmation modal before destructive actions: any <form data-confirm="…">
// is intercepted on first submit; the shared modal's Confirm button
// re-submits it for real. Must be wired before the loading-indicator
// listener below so that listener sees event.defaultPrevented on the
// intercepted (first) submit and skips disabling the button underneath the
// modal.
document.addEventListener("DOMContentLoaded", function () {
  const modalEl = document.getElementById("confirmActionModal");
  if (!modalEl || typeof bootstrap === "undefined") return;
  const modal = new bootstrap.Modal(modalEl);
  const bodyEl = document.getElementById("confirmActionModalBody");
  const confirmBtn = document.getElementById("confirmActionModalConfirm");
  let pendingForm = null;

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.dataset.confirmed === "true") return;
      event.preventDefault();
      pendingForm = form;
      bodyEl.textContent = form.dataset.confirm;
      confirmBtn.textContent = form.dataset.confirmLabel || "Confirmer";
      confirmBtn.className = "btn " + (form.dataset.confirmVariant || "btn-danger");
      modal.show();
    });
  });

  confirmBtn.addEventListener("click", function () {
    if (!pendingForm) return;
    modal.hide();
    pendingForm.dataset.confirmed = "true";
    pendingForm.requestSubmit();
  });
});

// Clickable table rows (list pages navigating via onclick="window.location=…")
// are otherwise invisible to keyboard/screen-reader users: a bare onclick on
// a <tr> has no accessible name and can't receive focus. Make each one a
// real keyboard target without touching every template that uses the
// pattern.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("tr[onclick]").forEach(function (row) {
    row.setAttribute("tabindex", "0");
    row.setAttribute("role", "link");
    row.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        row.click();
      }
    });
  });
});

// Loading feedback for regular (non-AJAX) form submissions: disable the
// submit button and show a spinner so a slow request (PDF generation, AI
// calls) doesn't look like a stalled click. Skips submits already
// intercepted above (defaultPrevented) and any form opting out via
// data-no-loading-indicator (pages that manage their own submit button
// state, e.g. the CV import page's fetch-based upload).
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form").forEach(function (form) {
    if (form.dataset.noLoadingIndicator === "true") return;
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      const submitButton = form.querySelector('button[type="submit"]');
      if (!submitButton || submitButton.disabled) return;
      submitButton.disabled = true;
      const label = submitButton.textContent.trim();
      submitButton.innerHTML =
        '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>' +
        (label ? " " + label : "");
    });
  });
});
