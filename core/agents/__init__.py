"""
core/agents/__init__.py — Moteur de créateurs IA autonomes

Des personnalités IA françaises génèrent et publient des vidéos
ultra-réalistes avec audio, selon un planning horaire, dans la galerie
communautaire.
"""

from core.agents.personas import AGENT_PERSONAS, AgentPersona, get_persona
from core.agents.scheduler import AgentScheduler, get_scheduler, set_scheduler

__all__ = [
    "AGENT_PERSONAS",
    "AgentPersona",
    "get_persona",
    "AgentScheduler",
    "get_scheduler",
    "set_scheduler",
]
