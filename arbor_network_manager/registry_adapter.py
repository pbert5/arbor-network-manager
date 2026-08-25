"""Canonical conversion from Registry accepted materialized state."""

from __future__ import annotations

from typing import Any, Mapping

from .model import snapshot_from_registry_mapping


class RegistryStateError(ValueError):
    pass


def snapshot_from_registry_state(
    value: Mapping[str, Any], *, providers: frozenset[str] = frozenset({"lan", "tailscale", "yggdrasil"})
):
    """Convert only accepted endpoint/reachability records into strong state.

    Registry records remain the authority. Provider observations are supplied
    later by RuntimeManager and are intentionally absent from this adapter.
    """
    if value.get("format") not in (None, "arbor-registry/accepted-state"):
        raise RegistryStateError("unsupported Registry state format")
    if int(value.get("version", 1)) != 1:
        raise RegistryStateError("unsupported Registry state version")
    accepted = value.get("accepted", [])
    if not isinstance(accepted, list):
        raise RegistryStateError("accepted Registry records must be a list")
    endpoints: list[dict[str, Any]] = []
    vertices: set[str] = set()
    revoked: set[str] = set()
    for record in accepted:
        if isinstance(record, Mapping) and record.get("schema") == "revocation":
            payload = record.get("payload", record)
            subject = payload.get("subject") if isinstance(payload, Mapping) else None
            if subject:
                revoked.add(str(subject))
    for record in accepted:
        if not isinstance(record, Mapping):
            raise RegistryStateError("Registry record must be an object")
        if record.get("status", "accepted") != "accepted" or record.get("quarantined", False):
            continue
        schema = record.get("schema")
        payload = record.get("payload", record)
        if schema == "revocation":
            continue
        if schema != "endpoint":
            continue
        if not isinstance(payload, Mapping):
            raise RegistryStateError("endpoint payload must be an object")
        required = ("node", "network", "provider", "address")
        if any(key not in payload for key in required):
            raise RegistryStateError("accepted endpoint is missing required fields")
        provider = str(payload["provider"])
        if provider not in providers:
            raise RegistryStateError(f"unknown endpoint provider: {provider}")
        endpoint_id = str(payload.get("id", record.get("recordId", "")))
        if endpoint_id in revoked:
            continue
        generation = payload.get("generation", record.get("generation"))
        if not isinstance(generation, int) or generation < 0:
            raise RegistryStateError("endpoint generation must be a non-negative integer")
        endpoint = {
            "node": str(payload["node"]), "network": str(payload["network"]),
            "provider": provider, "address": str(payload["address"]),
            "generation": generation,
            "capabilities": list(payload.get("capabilities", [])),
            "revoked": bool(payload.get("revoked", False)),
        }
        for source, target in (("identityGeneration", "identityGeneration"), ("sshHostGeneration", "sshHostGeneration")):
            if source in payload:
                endpoint[target] = int(payload[source])
        endpoints.append(endpoint)
        vertices.add(endpoint["node"])
    mapping = {
        "vertices": [{"node": node} for node in sorted(vertices)],
        "endpoints": endpoints,
        "edges": value.get("edges", []),
        "digest": str(value.get("digest", "")),
    }
    try:
        return snapshot_from_registry_mapping(mapping)
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryStateError(str(exc)) from exc
