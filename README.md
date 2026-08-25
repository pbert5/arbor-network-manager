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

## Development

```sh
python -m unittest discover -s tests -v
```
