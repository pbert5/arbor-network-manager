"""Provider-neutral network state and route planning primitives."""

from .model import (
    Edge, Endpoint, EndpointObservation, Health, NetworkSnapshot, Transit, Vertex,
    snapshot_from_compatibility_mapping, snapshot_from_mapping,
    snapshot_from_registry_mapping,
)
from .route import ExecutionBinding, RouteConstraints, RoutePlan, RouteSolver
from .registry_adapter import RegistryStateError, snapshot_from_registry_state

__all__ = [
    "Edge",
    "Endpoint",
    "EndpointObservation",
    "Health",
    "NetworkSnapshot",
    "Transit",
    "Vertex",
    "RouteConstraints",
    "ExecutionBinding",
    "RoutePlan",
    "RouteSolver",
    "snapshot_from_mapping",
    "snapshot_from_registry_mapping",
    "snapshot_from_compatibility_mapping",
    "RegistryStateError",
    "snapshot_from_registry_state",
]
