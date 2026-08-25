# Arbor Network Manager

Provider-neutral runtime network state, route solving, and reconciliation
contracts for Arbor. This repository does not implement a packet transport.
Providers own LAN, Tailscale, Yggdrasil, or future WireGuard/VLAN behavior.

The initial core is deliberately small: JSON-friendly endpoint/edge records,
explicit health and transit permissions, and deterministic constrained
Dijkstra solving. Revoked endpoint generations and unsupported capabilities
are never eligible for a route.

The runtime boundary is planned as a line-oriented Unix-socket protocol with
`status`, `local-identities`, `local-endpoints`, `health`, `capabilities`, and
`apply-peers` operations. Registry records are inputs, not provider authority;
private keys and credentials stay outside this repository and outside Nix.

## Public interfaces

`Endpoint` is an accepted provider advertisement. Its node, provider, network,
and generation identify the exact endpoint that may be used. `Edge` is a
provider observation joined with capability, health, endpoint-generation, and
transit authorization facts. `NetworkSnapshot` is an immutable reconciliation
input; it may carry accepted endpoint records for generation and revocation
validation.

`RouteSolver.solve(snapshot, source, target, constraints)` returns a
`RoutePlan`. Constraints include the requested capability, maximum hops,
excluded networks/providers, and whether private endpoints are required. A
plan contains the ordered nodes and exact edges, total cost, snapshot digest,
and rejection explanations. It is safe to persist as a route binding and
revalidate before execution.

The solver is deliberately provider-neutral. Providers report observations and
apply desired peer state; they do not select global routes. Registry adapters
must pass accepted, generation-aware, revocation-aware records only. No
credentials or private provider keys belong in these records.

## Compatibility and validation

The model accepts graph-only snapshots for small adapters and legacy callers.
When endpoint records are present, every edge must match a current, accepted
endpoint generation. This makes stale and revoked endpoint records unusable
without requiring a hidden cache.

## Development

```sh
python -m unittest discover -s tests -v
```

```sh
nix flake show
nix flake check
```
