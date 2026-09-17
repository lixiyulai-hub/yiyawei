export class ApiError extends Error {
  constructor(response, url) {
    super(`${response.status} ${response.statusText}`);
    this.name = "ApiError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.url = response.url || String(url);
  }
}

export function createApiClient(fetchImpl = globalThis.fetch) {
  if (typeof fetchImpl !== "function") {
    throw new TypeError("createApiClient requires a fetch implementation");
  }

  return async function api(path, options = {}) {
    const response = await fetchImpl(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      throw new ApiError(response, path);
    }
    return response.json();
  };
}
