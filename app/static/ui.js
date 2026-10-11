function setVisible(selector, visible) {
  document.querySelectorAll(selector).forEach((node) => {
    node.hidden = !visible;
  });
}

function syncEnvironmentForm() {
  const form = document.querySelector(".js-environment-form");
  if (!form) return;
  const type = form.querySelector("[name='environment_type']")?.value || "container";
  const auth = form.querySelector("[name='ssh_auth_method']")?.value || "password";
  const useSudo = form.querySelector("[name='use_sudo']")?.checked || false;
  const sudoFromSsh = form.querySelector("[name='sudo_password_from_ssh']")?.checked || false;
  const logMode = form.querySelector("[name='log_mode']");

  if (type === "direct" && logMode?.value === "container") {
    logMode.value = "file";
  }

  setVisible(".container-only", type === "container");
  setVisible(".direct-only", type === "direct");
  setVisible(".ssh-password-only", auth === "password");
  setVisible(".ssh-key-only", auth === "key");
  setVisible(".sudo-only", useSudo);
  setVisible(".sudo-password-only", useSudo && !sudoFromSsh);
}

function syncManualDsn() {
  const enabled = document.querySelector("[name='use_manual_dsn']")?.checked || false;
  setVisible(".manual-dsn-only", enabled);
}

document.addEventListener("DOMContentLoaded", () => {
  syncEnvironmentForm();
  syncManualDsn();
  document.querySelectorAll("[data-toggle], [name='use_manual_dsn']").forEach((node) => {
    node.addEventListener("change", () => {
      syncEnvironmentForm();
      syncManualDsn();
    });
  });
  document.querySelectorAll("[data-select-all]").forEach((node) => {
    node.addEventListener("change", () => {
      const group = node.getAttribute("data-select-all");
      document.querySelectorAll(`[data-select-item="${group}"]`).forEach((item) => {
        item.checked = node.checked;
      });
    });
  });
});
