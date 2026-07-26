"""generic_qa — a reusable SkillOpt environment for optimizing any skill.

Exposes :class:`GenericQAEnv` (the adapter SkillOpt's trainer drives) and
:class:`GenericQADataLoader`. Registration into SkillOpt's ``_ENV_REGISTRY`` is
handled by ``backend/skillopt_studio/skillopt/registration.py`` (which patches the
cloned editable checkout); this package only provides the implementation.
"""
from __future__ import annotations

from .env import GenericQAEnv, parse_answer
from .loader import GenericQADataLoader

# Convenience alias: SkillOpt adapters are conventionally named ``<Env>Adapter``.
GenericQAAdapter = GenericQAEnv

__all__ = ["GenericQAEnv", "GenericQAAdapter", "GenericQADataLoader", "parse_answer"]
