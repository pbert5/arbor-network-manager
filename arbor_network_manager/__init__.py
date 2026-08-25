"""Provider-neutral network state and route planning primitives."""

from .model import (
    Edge, Endpoint, EndpointObservation, Health, NetworkSnapshot, Transit, Vertex,
    snapshot_from_compatibility_mapping, snapshot_from_mapping,
    snapshot_from_registry_mapping,
)
from .route import RouteConstraints, RoutePlan, RouteSolver

__all__ = [
    "Edge",
    "Endpoint",
    "EndpointObservation",
    "Health",
    "NetworkSnapshot",
    "Transit",
    "Vertex",
    "RouteConstraints",
    "RoutePlan",
    "RouteSolver",
    "snapshot_from_mapping",
    "snapshot_from_registry_mapping",
    "snapshot_from_compatibility_mapping",
]
