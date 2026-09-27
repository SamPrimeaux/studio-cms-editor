# Workers VPC adoption plan

Workers VPC is an optional private-network bridge. It does not replace D1, R2,
KV, Workers service bindings, Queues, public APIs, or the existing storefront
Hyperdrive binding.

## Recommended IAM use

Start with a **VPC Service**, not a VPC Network. A VPC Service is constrained to
one host and port, which is the safer default for production Workers.

Good first targets:

- an Agent Sam API running on the GCP VM without a public listener;
- a Mac-tunnel helper that must be callable only when the Mac is online;
- private Postgres/MySQL through Hyperdrive;
- Blender, FreeCAD, render, or media-processing control APIs on a private host.

Do not place catalog reads, carts, D1, R2 media, checkout, or ordinary CMS calls
behind VPC. Those are already native or appropriately public Cloudflare paths.

## Required account-side setup

1. In Cloudflare, create or select a Tunnel whose `cloudflared` connector runs
   inside the same private network as the target.
2. Confirm the connector host can reach the target hostname/IP and port.
3. Give the operator creating services **Connectivity Directory Admin**. A
   deploy-only identity can use **Connectivity Directory Bind**.
4. Create the most narrowly scoped service possible:

```bash
npx wrangler vpc service create iam-private-api \
  --type http \
  --https-port 443 \
  --hostname api.internal.iam \
  --tunnel-id YOUR_TUNNEL_UUID \
  --cert-verification-mode verify_full
```

For private PostgreSQL, create a TCP VPC Service and connect it through
Hyperdrive:

```bash
npx wrangler vpc service create iam-private-postgres \
  --type tcp \
  --tcp-port 5432 \
  --app-protocol postgresql \
  --ipv4 10.0.0.5 \
  --tunnel-id YOUR_TUNNEL_UUID
```

5. Copy the returned service ID into `wrangler.production.toml`:

```toml
[[vpc_services]]
binding = "PRIVATE_API"
service_id = "YOUR_VPC_SERVICE_ID"
remote = true
```

6. Add `PRIVATE_API?: Fetcher` to the Worker environment and call it only from
   authenticated server-side routes. `worker/vpc.ts` contains the guarded
   adapter.

## When to use a VPC Network instead

Use a `vpc_networks` binding only for an operator gateway or agent that truly
needs runtime-selected destinations across several private subnets. It has a
much larger blast radius. Enforce destination allowlists in code and Zero Trust
Gateway policy before enabling it.

```toml
[[vpc_networks]]
binding = "IAM_PRIVATE_NETWORK"
network_id = "cf1:network"
remote = true
```

## Production gate

Workers VPC is beta. Before relying on it, verify tunnel redundancy, TLS,
timeouts, health checks, graceful failure, audit logging, and a native fallback
for every customer-facing path. Never make the public Inner Animals storefront
availability depend on a private connector.
