function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return "";
}

export async function apiFetch(path, options = {}) {
  const {compressJson = false, ...fetchOptions} = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers || {});
  let body = fetchOptions.body;

  if (body && typeof body !== "string" && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
    if (compressJson && new TextEncoder().encode(body).byteLength > 512 * 1024) {
      if (typeof CompressionStream !== "function") {
        throw new Error("Large painted projects require browser gzip support. Update your browser to slice while preserving exact brush boundaries.");
      }
      // Lossless transport only. The server still validates all expanded
      // polygons and enforces its own expanded-size and patch-count limits.
      const stream = new Blob([body]).stream().pipeThrough(new CompressionStream("gzip"));
      body = await new Response(stream).arrayBuffer();
      headers.set("Content-Encoding", "gzip");
    }
  }
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const csrf = getCookie("csrftoken");
    if (csrf) headers.set("X-CSRFToken", csrf);
  }

  const response = await fetch(path, {
    ...fetchOptions,
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
