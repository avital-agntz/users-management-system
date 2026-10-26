/**
 * Page behavior: registration, login/logout, and profile viewing/editing.
 * All user-provided values are rendered with textContent or input.value,
 * never as HTML.
 */

import {
  ApiError,
  apiRequest,
  clearAccessToken,
  onUnauthorized,
  setAccessToken,
} from "./api.js";

const elements = {
  status: document.getElementById("status-message"),
  registerSection: document.getElementById("register-section"),
  loginSection: document.getElementById("login-section"),
  profileSection: document.getElementById("profile-section"),
  registerForm: document.getElementById("register-form"),
  loginForm: document.getElementById("login-form"),
  profileForm: document.getElementById("profile-form"),
  logoutButton: document.getElementById("logout-button"),
  profileFirstName: document.getElementById("profile-first-name"),
  profileLastName: document.getElementById("profile-last-name"),
  profileEmail: document.getElementById("profile-email"),
};

const PENDING_LABELS = {
  "register-form": "Creating account…",
  "login-form": "Logging in…",
  "profile-form": "Saving…",
};

// The last profile returned by the API; used to detect what the user changed.
let currentProfile = null;

// ---------- Status messages ----------

function showMessage(text, kind = "info") {
  elements.status.textContent = text;
  elements.status.dataset.kind = kind;
}

function clearMessage() {
  elements.status.textContent = "";
  delete elements.status.dataset.kind;
}

function showError(error) {
  if (error instanceof ApiError) {
    showMessage(error.message, "error");
  } else {
    console.error(error);
    showMessage("Something unexpected happened. Please try again.", "error");
  }
}

// ---------- Pending state ----------

/**
 * Run a form's request while its controls are disabled.
 * The busy flag ignores repeated submits (double clicks, Enter key)
 * until the first request finishes.
 */
async function whilePending(form, action) {
  if (form.dataset.busy === "true") {
    return;
  }
  const controls = Array.from(form.elements);
  const button = form.querySelector("button[type=submit]");
  const label = button.textContent;
  // Read values before disabling: disabled inputs are left out of FormData.
  const values = formValues(form);

  form.dataset.busy = "true";
  form.setAttribute("aria-busy", "true");
  controls.forEach((control) => (control.disabled = true));
  button.textContent = PENDING_LABELS[form.id];
  try {
    await action(values);
  } finally {
    form.dataset.busy = "false";
    form.removeAttribute("aria-busy");
    controls.forEach((control) => (control.disabled = false));
    button.textContent = label;
  }
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

// ---------- Views ----------

function showLoggedOutView() {
  elements.profileSection.hidden = true;
  elements.registerSection.hidden = false;
  elements.loginSection.hidden = false;
}

function showProfileView() {
  elements.registerSection.hidden = true;
  elements.loginSection.hidden = true;
  elements.profileSection.hidden = false;
}

function renderProfile(profile) {
  currentProfile = profile;
  elements.profileFirstName.textContent = profile.first_name;
  elements.profileLastName.textContent = profile.last_name;
  elements.profileEmail.textContent = profile.email;

  const inputs = elements.profileForm.elements;
  inputs.first_name.value = profile.first_name;
  inputs.last_name.value = profile.last_name;
  inputs.email.value = profile.email;
}

function clearSession() {
  clearAccessToken();
  currentProfile = null;
  elements.profileFirstName.textContent = "";
  elements.profileLastName.textContent = "";
  elements.profileEmail.textContent = "";
  elements.profileForm.reset();
  showLoggedOutView();
}

// An authenticated request returned 401: the token expired or is invalid.
onUnauthorized(() => {
  clearSession();
  elements.loginForm.elements.email.focus();
});

// ---------- Registration ----------

elements.registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = elements.registerForm;

  whilePending(form, async (values) => {
    clearMessage();
    try {
      const user = await apiRequest("/register", {
        method: "POST",
        body: {
          first_name: values.first_name,
          last_name: values.last_name,
          email: values.email,
          password: values.password,
        },
      });
      form.reset();
      elements.loginForm.elements.email.value = user.email;
      showMessage(`Account created for ${user.email}. Please log in.`, "success");
    } catch (error) {
      // Keep the entered values so the user can fix them; never keep the password.
      form.elements.password.value = "";
      showError(error);
    }
  });
});

// ---------- Login and logout ----------

elements.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = elements.loginForm;

  whilePending(form, async (values) => {
    clearMessage();
    try {
      const result = await apiRequest("/login", {
        method: "POST",
        body: { email: values.email, password: values.password },
      });
      setAccessToken(result.access_token);
      form.reset();
      const profile = await apiRequest("/profile", { auth: true });
      renderProfile(profile);
      showProfileView();
      showMessage(`Welcome, ${profile.first_name}.`, "success");
    } catch (error) {
      form.elements.password.value = "";
      showError(error);
    }
  });
});

elements.logoutButton.addEventListener("click", () => {
  clearSession();
  showMessage("You have been logged out.", "info");
});

// ---------- Profile editing ----------

/** Return only the fields whose values differ from the saved profile. */
function changedFields(values) {
  const candidate = {
    first_name: values.first_name.trim(),
    last_name: values.last_name.trim(),
    email: values.email.trim(),
  };
  return Object.fromEntries(
    Object.entries(candidate).filter(([field, value]) => value !== currentProfile[field]),
  );
}

elements.profileForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = elements.profileForm;

  whilePending(form, async (values) => {
    clearMessage();
    const changes = changedFields(values);
    if (Object.keys(changes).length === 0) {
      showMessage("No changes to save.", "info");
      return;
    }
    try {
      const profile = await apiRequest("/update", {
        method: "PUT",
        body: changes,
        auth: true,
      });
      renderProfile(profile);
      showMessage("Profile saved.", "success");
    } catch (error) {
      // On validation or conflict errors, leave the entered values in place.
      showError(error);
    }
  });
});

// The buttons start disabled in the HTML; enable them now that handlers exist.
document.querySelectorAll("button[disabled]").forEach((button) => (button.disabled = false));
