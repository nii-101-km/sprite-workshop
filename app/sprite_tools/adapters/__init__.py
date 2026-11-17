"""Explicit registered model implementations; no discovery, imports from workdir, or IO."""
from .base import ComfyGraphAdapter
from .qwen import QwenAdapter
from .klein import KleinAdapter

_ADAPTERS = {adapter.model_id: adapter for adapter in (QwenAdapter(), KleinAdapter())}


def models() -> tuple[str, ...]:
    return tuple(_ADAPTERS)


def get_adapter(model: str) -> ComfyGraphAdapter:
    if not isinstance(model, str) or model not in _ADAPTERS:
        raise ValueError(f'Unknown model {model!r}; supported: {list(_ADAPTERS)}')
    return _ADAPTERS[model]
