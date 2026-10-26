/**
 * Shared API-request helper: JSON encoding, authentication headers, and
 * turning every failure into one readable message.
 */

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from "./config.js";

const UNAVAILABLE_MESSAGE =
  "The application cannot be reached right now. Please try again shortly.";

const FIELD_LABELS = {
  first_name: "First name",
  last_name: "Last name",
  email: "Email",
  password: "Password",
};

// The token lives only in this variable (browser memory), never in storage.
let accessToken = null;
let unauthorizedHandler = () => {};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function setAccessToken(token) {
  accessToken = token;
}

export function clearAccessToken() {
  accessToken = null;
}

/** Register what to do when an authenticated request is rejected (401). */
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

/**
 * Send a request to the API and return the parsed JSON body.
 * Throws ApiError with a message that is safe to show to the user.
 */
export async function apiRequest(path, { method = "GET", body, auth = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    if (accessToken === null) {
      unauthorizedHandler();
      throw new ApiError("Please log in again.", 401);
    }
    headers.Authorization = `Bearer ${accessToken}`;
  }

  let response;
  try {
    response = await fetch(API_BASE_URL + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    // Network failure, refused connection, or timeout.
    throw new ApiError(UNAVAILABLE_MESSAGE, 0);
  }

  // A proxy in front of the API answers 502/503/504 when the API is down.
  if ([502, 503, 504].includes(response.status)) {
    throw new ApiError(UNAVAILABLE_MESSAGE, response.status);
  }

  const data = await readJson(response);
  if (response.ok) {
    return data;
  }

  if (response.status === 401 && auth) {
    unauthorizedHandler();
    throw new ApiError("Your session has expired. Please log in again.", 401);
  }
  throw new ApiError(describeError(response.status, data), response.status);
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** Convert FastAPI error bodies into plain-language text. */
function describeError(status, data) {
  const detail = data?.detail;

  // 401/409 and other HTTPExceptions: detail is already a readable string.
  if (typeof detail === "string") {
    return detail;
  }

  // 422 validation errors: detail is a list of {loc, msg} objects.
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map(describeValidationIssue).join("\n");
  }

  if (status >= 500) {
    return "Something went wrong on the server. Please try again.";
  }
  return `The request failed (status ${status}).`;
}

function describeValidationIssue(issue) {
  const field = Array.isArray(issue?.loc) ? issue.loc[issue.loc.length - 1] : null;
  const message = String(issue?.msg ?? "Invalid value.").replace(/^Value error, /, "");
  const label = FIELD_LABELS[field];
  return label ? `${label}: ${message}` : message;
}
