"""Contract v2 integration: the in-process backend adapter (phase 1)."""

from .backend import Backend, make_backend
from .seed import FIXED_NOW, build_store_from_scenario

__all__ = ["FIXED_NOW", "Backend", "build_store_from_scenario", "make_backend"]
