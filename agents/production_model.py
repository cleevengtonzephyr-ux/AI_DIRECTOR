"""
AI DIRECTOR — Production Model (Phase P2.2, MASTER PROMPT V2)

Source UNIQUE de vérité pour le modèle Higgsfield réellement utilisé en
production. Toute couche qui a besoin du job_type de production
(agents/video_agent.py, agents/generation_approval_gate.py et, pour son
rôle informatif V1, agents/cost_engine.py) importe cette constante au
lieu de la recopier — évite la divergence qui existait avant P2.2,
où agents/cost_engine.py interrogeait silencieusement
"cinematic_studio_video_4_0" (un WORKFLOW V1, agents/planner.py) au
lieu du vrai MODÈLE de production.

Ne PAS confondre avec un WORKFLOW V1 (`VideoPlan.workflow`, ex.
"cinematic_studio_video_4_0") : ce module ne concerne que le MODÈLE
réel interrogé pour le coût et la génération (vérifié réel, Phase A).
"""

PRODUCTION_MODEL = "seedance_2_0"
