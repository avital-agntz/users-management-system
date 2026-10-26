/**
 * The only place the frontend's API address is configured.
 *
 * An empty string means "same origin": requests go to the server that served
 * this page (the local dev server now, Nginx on EC2 later), which forwards them
 * to FastAPI. Set a full URL such as "http://127.0.0.1:8000" only if the API is
 * served from a different origin, which would also require CORS on the backend.
 */
export const API_BASE_URL = "";

// Give up on a request after this long and treat the API as unavailable.
export const REQUEST_TIMEOUT_MS = 10000;
