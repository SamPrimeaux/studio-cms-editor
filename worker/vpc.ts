/**
 * Optional Workers VPC adapter.
 *
 * Keep storefront requests on native Cloudflare services. Use this adapter only
 * for private HTTP services that sit behind an approved VPC Service binding.
 */
export interface PrivateServiceBinding {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

export async function fetchPrivateJson<T>(
  service: PrivateServiceBinding | undefined,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (!service) throw new Error("Workers VPC binding PRIVATE_API is not configured");
  if (!path.startsWith("/")) throw new Error("Private service paths must begin with /");

  const response = await service.fetch(`http://private.internal${path}`, {
    ...init,
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`Private service returned ${response.status}`);
  return response.json() as Promise<T>;
}
