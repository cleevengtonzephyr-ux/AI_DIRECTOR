"""
Fixtures de TEST (Phase D) pour le chemin réel de la Gate.

Depuis la Phase D, `GenerationApprovalGate` renvoie BLOCKED pour tout
Provider qui n'est pas un mock de test reconnu (vrai
`HiggsfieldProvider`, ses sous-classes, sous-classes instrumentées du
Mock, Provider inconnu, wrapper) tant qu'un plafond par requête n'est
pas EXPLICITEMENT configuré ou qu'aucun `ReleaseCandidateIdentityLock`
n'est injecté. Les tests qui utilisent un tel Provider configurent donc
explicitement ces deux réglages avec les fixtures ci-dessous -- des
verrous RÉELS, liés au contenu exact évalué, jamais permissifs.

TEST UNIQUEMENT : aucun module de production n'importe ce fichier
(vérifié par tests/test_phase_d_cost_fail_closed.py), `director.py`
ne configure aucun plafond. Aucune valeur ci-dessous n'est un plafond
de production ni une recommandation de montant.
"""

import dataclasses
import hashlib
from contextlib import contextmanager
from unittest.mock import patch

from agents.generation_approval_gate import GenerationApprovalGate, GenerationRequest
from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError
from integrations.higgsfield.mock_provider import MockHiggsfieldProvider
from agents.release_candidate_identity_lock import (
    VIDEO_005_RELEASE_CANDIDATE,
    ReleaseCandidateContract,
    ReleaseCandidateIdentityLock,
    _sha256_of_file,
)

# Plafond de FIXTURE : couvre les coûts simulés de ces tests (5, 10,
# 22.5, 67.5 crédits). Jamais utilisé hors de tests/.
FIXTURE_MAX_COST_CREDITS_PER_REQUEST = 100.0


def fixture_contract_for(request: GenerationRequest) -> ReleaseCandidateContract:
    """Contrat de FIXTURE : le contenu EXACT de `request` (prompt, avatar
    et référence visage relus sur disque à cet instant)."""

    face = next(ref for ref in request.image_references if ref.role == "face_reference")
    return ReleaseCandidateContract(
        request_id=request.request_id,
        job_type=request.job_type,
        duration=request.duration,
        resolution=request.resolution,
        aspect_ratio=request.aspect_ratio,
        prompt_sha256=hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
        prompt_chars=len(request.prompt),
        prompt_lines=len(request.prompt.splitlines()),
        avatar_master_sha256=_sha256_of_file(request.start_image.source),
        face_reference_sha256=_sha256_of_file(face.source),
    )


class FixtureContentsIdentityLock(ReleaseCandidateIdentityLock):
    """Identity Lock de FIXTURE pour plusieurs contenus ÉNUMÉRÉS (tests
    qui évaluent plusieurs requêtes sur une même Gate). Strict : une
    requête n'est acceptée que si elle correspond EXACTEMENT à l'un des
    contrats (même vérification que `ReleaseCandidateIdentityLock`) ;
    sinon, les violations du contrat de même `request_id` (ou du premier)
    sont renvoyées."""

    def __init__(self, contracts):
        contracts = tuple(contracts)
        super().__init__(contracts[0])
        self.contracts = contracts

    def violations(self, request):
        first = same_id = None
        for contract in self.contracts:
            found = ReleaseCandidateIdentityLock(contract).violations(request)
            if not found:
                return []
            if first is None:
                first = found
            if same_id is None and contract.request_id == request.request_id:
                same_id = found
        return list(same_id if same_id is not None else first)


def fixture_identity_lock_for(*requests: GenerationRequest) -> ReleaseCandidateIdentityLock:
    """Identity Lock de FIXTURE verrouillé sur le contenu EXACT de
    `requests` -- jamais permissif : toute divergence ultérieure reste
    refusée. Une seule requête : un `ReleaseCandidateIdentityLock`
    ordinaire ; plusieurs : `FixtureContentsIdentityLock`."""

    contracts = [fixture_contract_for(request) for request in requests]
    if len(contracts) == 1:
        return ReleaseCandidateIdentityLock(contracts[0])
    return FixtureContentsIdentityLock(contracts)


def fixture_real_path_gate_kwargs(*requests: GenerationRequest) -> dict:
    """Arguments EXPLICITES de Gate pour un Provider non reconnu comme
    mock : plafond de FIXTURE + Identity Lock lié à `requests`."""

    return {
        "identity_lock": fixture_identity_lock_for(*requests),
        "max_cost_credits_per_request": FIXTURE_MAX_COST_CREDITS_PER_REQUEST,
    }


def fixture_video_005_identity_lock(**overrides) -> ReleaseCandidateIdentityLock:
    """Identity Lock de FIXTURE sur le contenu CANONIQUE de Video 005
    (prompt et assets inchangés), avec seulement les paramètres
    `overrides` propres au test (ex. `duration=5`) -- pour les requêtes
    construites plus tard par le Director/VideoAgent."""

    return ReleaseCandidateIdentityLock(
        dataclasses.replace(VIDEO_005_RELEASE_CANDIDATE, **overrides)
    )


@contextmanager
def fixture_ceiling_on_director_gate(ceiling=FIXTURE_MAX_COST_CREDITS_PER_REQUEST):
    """Configure EXPLICITEMENT, pour la durée du bloc, le plafond de
    FIXTURE sur la Gate que construit `AIDirector._build_default_chain()`.
    Le Director lui-même n'en configure aucun : sans ce bloc, sa chaîne
    réelle reste BLOCKED."""

    import director as director_module

    def _gate_with_test_ceiling(*args, **kwargs):
        assert "max_cost_credits_per_request" not in kwargs, (
            "director.py must never configure a per-request ceiling itself."
        )
        return GenerationApprovalGate(*args, max_cost_credits_per_request=ceiling, **kwargs)

    with patch.object(director_module, "GenerationApprovalGate", _gate_with_test_ceiling):
        yield


# ----------------------------------------------------------------------
# Instrumentation de create_job() HORS du Provider (Phase D)
# ----------------------------------------------------------------------
#
# Depuis la Phase D, `GenerationJobService.execute()` refuse, avant toute
# autre étape, tout Provider qui n'est pas une implémentation
# explicitement sûre (Mock reconnu, ou vrai `HiggsfieldProvider` exact) :
# un Provider de test qui redéfinit `create_job()` ne l'atteint donc
# plus. Les tests qui observaient l'instant de l'appel utilisent le Mock
# reconnu et placent leur instrumentation sur `gate.in_flight()` : le
# bloc que `execute()` ouvre juste avant `create_job()` (après la
# consommation de l'autorisation et le marqueur durable) et referme
# juste après, sans rien d'autre à l'intérieur. Aucun code de production
# ne lit ces attributs.


def counting_mock_provider(*, refuse=False, on_create=None, after_create_job=None, **mock_kwargs):
    """Mock RECONNU (instance exacte de `MockHiggsfieldProvider`) portant
    les réglages lus par `install_create_job_probe()` : `create_calls`
    (compteur), `refuse`, `on_create(params)`, `after_create_job()`."""

    provider = MockHiggsfieldProvider(**mock_kwargs)
    provider.create_calls = 0
    provider.refuse = refuse
    provider.on_create = on_create
    provider.after_create_job = after_create_job
    return provider


def install_create_job_probe(gate, provider):
    """Enveloppe `gate.in_flight()` pour observer chaque appel de
    `provider.create_job()` par `GenerationJobService.execute()` :

    - à l'entrée (instant de l'appel) : `provider.create_calls += 1`, puis
      `provider.on_create({"request_id": ...})`, puis -- si
      `provider.refuse` -- refus identique à celui du vrai Provider
      (`HiggsfieldRealGenerationDisabledError`, avant tout appel client ;
      `create_job()` n'est alors pas appelé) ;
    - à la sortie normale (juste après le retour de `create_job()`, avant
      `mark_executed()`) : `provider.after_create_job()`.

    Renvoie `gate`."""

    original_in_flight = gate.in_flight

    @contextmanager
    def probed_in_flight(request_id):
        with original_in_flight(request_id):
            provider.create_calls = getattr(provider, "create_calls", 0) + 1
            if getattr(provider, "on_create", None) is not None:
                provider.on_create({"request_id": request_id})
            if getattr(provider, "refuse", False):
                raise HiggsfieldRealGenerationDisabledError("mock refusal before any client call")
            yield
            if getattr(provider, "after_create_job", None) is not None:
                provider.after_create_job()

    gate.in_flight = probed_in_flight
    return gate
