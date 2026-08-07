"""
core/agents/__init__.py — Moteur de créateurs IA autonomes

Des personnalités IA françaises génèrent et publient des vidéos
ultra-réalistes avec audio, selon un planning horaire, dans la galerie
communautaire (v9.3 : + vie sociale — likes et abonnements rythmés).
"""

from core.agents.personas import AGENT_PERSONAS, AgentPersona, get_persona
from core.agents.scheduler import AgentScheduler, get_scheduler, set_scheduler
from core.agents.social import AgentSocial

__all__ = [
    "AGENT_PERSONAS",
    "AgentPersona",
    "get_persona",
    "AgentScheduler",
    "get_scheduler",
    "set_scheduler",
    "AgentSocial",
]
