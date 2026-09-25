function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return "";
}

export async function apiFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  let body = options.body;

  if (body && typeof body !== "string" && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const csrf = getCookie("csrftoken");
    if (csrf) headers.set("X-CSRFToken", csrf);
  }

  const response = await fetch(path, {
    ...options,
    method,
    headers,
    body,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `MakerVault request failed (${response.status}).`);
    error.status = response.status;
    error.fields = data.fields || {};
    throw error;
  }
  return data;
}
