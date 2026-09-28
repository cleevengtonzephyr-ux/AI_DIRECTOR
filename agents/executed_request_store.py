"""
AI DIRECTOR — Executed Request Store (Phase P2.15, MASTER PROMPT V2)

Résout la lacune identifiée en P2.14 : `GenerationApprovalGate` ne
retenait les `request_id` déjà exécutés qu'en mémoire
(`_executed_request_ids: Set[str]`), perdue à chaque redémarrage du
processus Python. Ce module fournit le mécanisme de persistance
minimal nécessaire pour que ce fait survive un redémarrage — rien de
plus.

DEUX implémentations, interchangeables (mêmes méthodes
`is_executed()`/`mark_executed()`), pour ne RIEN changer au
comportement des 314 tests existants qui construisent
`GenerationApprovalGate(provider)` sans argument supplémentaire :

- `InMemoryExecutedRequestStore` : reproduit exactement l'ancien
  comportement (un `set[str]` en mémoire). C'est le défaut de
  `GenerationApprovalGate` si aucun store n'est injecté — AUCUNE
  écriture disque, AUCUNE régression pour le code/tests existants.
- `FileExecutedRequestStore` : persistance JSON locale, atomique en
  écriture (fichier temporaire + `os.replace`), utilisée par le SEUL
  chemin réel de production (`AIDirector._build_default_report_
  service()`), car ce projet n'est actuellement composé que de
  scripts/CLI à courte durée de vie (aucun processus long-vivant,
  aucun serveur/daemon trouvé dans le dépôt) — sans persistance, la
  protection anti-rejeu ne protège RIEN entre deux invocations
  réelles.

RÈGLE ABSOLUE — FAIL CLOSED :
Un état de replay guard absent (fichier inexistant) signifie
légitimement "rien n'a encore été exécuté" — CE N'EST PAS une
corruption. Un état présent mais illisible/mal formé lève
`ExecutedRequestStoreCorruptedError` plutôt que de renvoyer
silencieusement `False` : c'est à `GenerationApprovalGate.evaluate()`
de transformer cette incertitude en `BLOCKED`, JAMAIS en `APPROVED`
(cf. agents/generation_approval_gate.py).

CE QUI EST PERSISTÉ — volontairement minimal :
`{"executed_requests": {"<id>": {"executed_at": <iso8601>}},
"unknown_requests": {"<id>": {"marked_at": <iso8601>, "reason": <str>}}}`.
Le fait qu'une requête a déjà été exécutée, ou qu'une tentative a
laissé un état ambigu (P2.20) — JAMAIS une autorisation réutilisable :
aucun secret, credential, token, prompt complet, ni objet
RealGenerationAuthorization n'est écrit ici. Ce store ne peut donc
jamais, par construction, réactiver automatiquement une génération —
il ne sait que dire "non, celle-ci a déjà eu lieu" ou "non, son état
est incertain".

LIMITES CONNUES EN P2.15, DÉSORMAIS ADRESSÉES EN P2.20 :
- Le verrou inter-processus (TOCTOU, P2.16) est désormais fermé par
  `agents/critical_section_lock.py`, appelé par
  `GenerationJobService.execute()` AUTOUR de la séquence complète
  check-not-executed -> approbation finale -> create_job ->
  mark_executed. Ce module (executed_request_store.py) reste
  responsable UNIQUEMENT du registre lui-même, jamais de
  l'exclusion mutuelle.
- Le crash entre un `create_job()` réel réussi et `mark_executed()`
  (P2.19/P2.20) est désormais représenté explicitement par un second
  registre, `unknown_requests` (cf. `is_unknown()`/`mark_unknown()`
  ci-dessous), plutôt que silencieusement absent de tout registre.
  Une requête marquée "unknown" reste néanmoins BLOQUÉE pour tout
  rejeu automatique (cf. `GenerationApprovalGate.evaluate()`,
  `GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN`) — ce module
  ne prétend PAS pouvoir déterminer si le job Higgsfield sous-jacent a
  réellement été créé, seulement qu'une tentative a eu lieu et que sa
  comptabilisation locale n'a pas pu être confirmée de façon fiable.

PHASE P3.89 (GAP #1 de P3.88) — IDENTITÉ D'EXÉCUTION PERSISTÉE :
Avant P3.89, seul `request_id` était persisté ; le `job_id` renvoyé
par `create_job()` ne vivait qu'en mémoire (et, en UNKNOWN, dans le
texte libre `reason`). Un crash pendant le polling rendait le job créé
(et facturé) introuvable localement. Désormais `mark_executed()` et
`mark_unknown()` acceptent `job_id`, écrit comme champ structuré DANS
LA MÊME écriture atomique que l'enregistrement anti-rejeu (jamais une
seconde écriture séparée), et `recorded_job_id()` le relit pour CE
`request_id` uniquement. Un `job_id` différent pour une requête déjà
enregistrée est refusé (`ExecutedRequestStoreConflictError`), jamais
écrasé. Ce champ est une TRACE, jamais une autorisation :
`is_executed()`/`is_unknown()` (seules lectures utilisées par
`GenerationApprovalGate.evaluate()`) n'en dépendent pas.

LIMITE RESTANTE, TOUJOURS NON MASQUÉE :
- Un crash exactement pendant l'écriture de `mark_unknown()` elle-même
  (après un échec de `mark_executed()`) n'est PAS couvert par ce
  module : dans ce cas, `GenerationJobService` lève une exception
  distincte et non capturée
  (`CriticalStateUnknownAndUnrecordedError`) plutôt que de prétendre
  avoir enregistré quoi que ce soit. Depuis P3.91, le marqueur
  write-ahead (ci-dessous) est déjà persisté à ce stade : la requête
  reste UNKNOWN même dans ce cas.

PHASE P3.91 — DEUX RISQUES DÉMONTRÉS EN P3.90, FERMÉS ICI :
1. Write-ahead (`in_flight()`, context manager autour de
   `create_job()`) : `GenerationJobService` persiste dans
   `unknown_requests` un enregistrement `{"in_flight": true, ...}`, lu
   comme UNKNOWN par `is_unknown()`. `mark_executed()` le retire DANS
   LA MÊME écriture atomique ; `mark_unknown()` le transforme en
   UNKNOWN ordinaire. Le seul retour arrière est interne au bloc
   (refus `HiggsfieldRealGenerationDisabledError` du Provider, avant
   tout appel client) et ne peut viser que le marqueur écrit par CE
   bloc : aucune méthode ne retire un UNKNOWN existant (invariant
   P3.38 inchangé). Un crash entre `create_job()` et `mark_executed()`
   laisse donc une trace bloquante, jamais une absence de trace.
2. Verrou GLOBAL du fichier (`<path>.lock`, création exclusive
   `O_CREAT | O_EXCL`, bibliothèque standard uniquement) : TOUTE
   séquence lecture -> décision -> modification -> écriture atomique
   (fichier temporaire + fsync + `os.replace`) s'exécute sous ce
   verrou, ainsi que chaque lecture (évite aussi, sous Windows, les
   `PermissionError` entre un lecteur et `os.replace`). Attente
   bornée (`lock_timeout_seconds`) puis
   `ExecutedRequestStoreLockTimeoutError` -- sous-classe de
   `ExecutedRequestStoreCorruptedError`, donc `BLOCKED` au Gate (fail
   closed). Un verrou orphelin (processus tué) n'est JAMAIS supprimé
   automatiquement : son contenu (`pid`, `acquired_at`) n'est qu'une
   information de diagnostic pour la revue humaine. Même politique que
   `agents/critical_section_lock.py` ; mécanisme volontairement
   indépendant (aucun import de ce module ni du sous-système
   certificats).

PHASE B — USAGE UNIQUE DE `RealGenerationAuthorization` :
Registre SÉPARÉ, exclusivement dédié à la consommation des
autorisations (`FileAuthorizationConsumptionRegistry`, fichier
`consumed_authorizations.json` dans le MÊME dossier d'état, verrou
propre `consumed_authorizations.json.lock`). `executed_requests.json`
reste inchangé et ne contient toujours AUCUNE donnée ni référence
d'autorisation (invariant P3.89). Chaque store expose son registre via
l'attribut `authorization_registry` (non appelable : l'API publique du
store est inchangée).
- Contenu : uniquement `sha256(authorization_id)` -> `{"request_id",
  "consumed_at"}`. Jamais l'objet d'autorisation, `note`,
  `authorized_by_human`, `authorized_at`, le prompt ni aucun contenu.
- `consume()` : vérification + inscription dans UNE écriture atomique
  (fichier temporaire + fsync + `os.replace`) sous le verrou du
  registre -- sûr entre threads et entre processus partageant ce
  dossier. Déjà consommée -> `AuthorizationAlreadyConsumedError`.
  Corruption, verrou indisponible, écriture impossible -> exception :
  `create_job()` n'est jamais atteint.
- PAS de transaction commune avec `executed_requests.json` : la
  consommation est écrite AVANT le marqueur write-ahead. Un arrêt entre
  les deux brûle l'autorisation sans démarrer l'exécution -- échec
  fermé assumé (une nouvelle autorisation humaine est requise).
- Définitive : aucune méthode ne retire une consommation, aucune purge
  automatique ; le retour arrière du marqueur (refus du Provider) ne
  touche jamais ce registre.
- Portée honnête : UNE machine, UN dossier d'état partagé ; aucune
  garantie multi-machine. Supprimer le fichier à la main rend de
  nouveau utilisables les autorisations qu'il consignait.
  `InMemoryAuthorizationConsumptionRegistry` (défaut du store en
  mémoire) est sûr entre threads d'un même processus mais NE SURVIT PAS
  à un redémarrage.
- Non couvert : aucun lien autorisation <-> hashes prompt/avatar/
  référence visage, aucune identité authentifiée.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Set

from integrations.higgsfield.errors import HiggsfieldRealGenerationDisabledError

# Phase P3.98 (D3) : nouvel essai borné de la suppression du verrou à la
# libération (cf. `FileExecutedRequestStore._locked()`).
_LOCK_RELEASE_RETRY_SECONDS = 1.0
_LOCK_RELEASE_RETRY_INTERVAL_SECONDS = 0.005


class ExecutedRequestStoreCorruptedError(RuntimeError):
    """
    Levée quand l'état persistant du replay guard existe mais ne peut
    pas être lu/interprété de façon fiable (JSON invalide, forme
    inattendue). Ne signifie JAMAIS "rien n'a été exécuté" : c'est à
    l'appelant (GenerationApprovalGate.evaluate()) de refuser
    l'approbation tant que cette incertitude n'est pas résolue.
    """


class ExecutedRequestStoreLockTimeoutError(ExecutedRequestStoreCorruptedError):
    """
    Phase P3.91 — le verrou global du fichier n'a pas pu être acquis
    dans le délai imparti (autre écriture en cours, ou verrou orphelin
    laissé par un processus tué). L'état ne peut donc pas être vérifié :
    sous-classe de `ExecutedRequestStoreCorruptedError` pour que
    `GenerationApprovalGate.evaluate()` renvoie `BLOCKED`, jamais
    `APPROVED`. Le verrou n'est jamais supprimé automatiquement.
    """


class ExecutedRequestStoreConflictError(RuntimeError):
    """
    Phase P3.89 — Levée quand un `job_id` différent de celui déjà
    enregistré est présenté pour le même `request_id`. L'identité
    d'exécution enregistrée n'est jamais écrasée : dans
    `GenerationJobService`, cet échec de `mark_executed()` suit le
    chemin UNKNOWN existant (fail closed).
    """


class AuthorizationAlreadyConsumedError(ExecutedRequestStoreConflictError):
    """
    Phase B — l'autorisation présentée a déjà été consommée par une
    tentative d'exécution antérieure. Levée sous le verrou du registre,
    avant le marqueur write-ahead, donc avant tout `create_job()`.
    """


class AuthorizationRegistryCorruptedError(ExecutedRequestStoreCorruptedError):
    """Phase B — registre de consommation illisible ou mal formé.
    Sous-classe de `ExecutedRequestStoreCorruptedError` : BLOCKED au
    Gate, jamais APPROVED ; jamais réinitialisé silencieusement."""


class AuthorizationRegistryLockTimeoutError(AuthorizationRegistryCorruptedError):
    """Phase B — verrou du registre non acquis dans le délai (écriture
    concurrente ou verrou orphelin, jamais supprimé automatiquement)."""


class InvalidAuthorizationIdError(ValueError):
    """Phase B — `authorization_id` absent ou mal formé : refusé avant
    toute lecture/écriture du registre."""


_AUTHORIZATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def validate_authorization_id(authorization_id: Any) -> str:
    if not isinstance(authorization_id, str) or not _AUTHORIZATION_ID_PATTERN.fullmatch(
        authorization_id
    ):
        raise InvalidAuthorizationIdError(
            f"authorization_id {authorization_id!r} is not a valid identifier "
            f"(1-128 chars, [A-Za-z0-9._:-], starting alphanumeric)."
        )
    return authorization_id


def _checked_job_id(job_id: Optional[str]) -> Optional[str]:
    if job_id is not None and (not isinstance(job_id, str) or not job_id):
        raise ValueError(f"job_id must be None or a non-empty str, got {job_id!r}")
    return job_id


def _unknown_job_id(job_id: Optional[str]) -> Optional[str]:
    # Chemin de secours UNKNOWN : l'enregistrement anti-rejeu prime
    # toujours sur la trace -- un `job_id` mal formé n'empêche jamais
    # de consigner l'ambiguïté (il reste visible dans `reason`).
    return job_id if isinstance(job_id, str) and job_id else None


def _merge_job_id(previous: Optional[str], job_id: Optional[str], request_id: str) -> Optional[str]:
    if previous is not None and job_id is not None and previous != job_id:
        raise ExecutedRequestStoreConflictError(
            f"Request '{request_id}' is already recorded with job_id "
            f"{previous!r}; refusing to record foreign job_id {job_id!r}."
        )
    return previous if job_id is None else job_id


class InMemoryExecutedRequestStore:
    """
    Comportement IDENTIQUE à l'ancien `_executed_request_ids` de
    GenerationApprovalGate (Phase G) — en mémoire uniquement, perdu à
    chaque redémarrage du processus. Défaut de GenerationApprovalGate
    quand aucun store n'est injecté explicitement : garantit que les
    314 tests existants (et tout code appelant `GenerationApprovalGate
    (provider)` sans 3e argument) ne changent pas de comportement.

    Phase B : `authorization_registry` est un registre de consommation
    EN MÉMOIRE (sûr entre threads, portée limitée au processus) -- il ne
    fournit AUCUNE consommation durable après redémarrage.
    """

    def __init__(self) -> None:
        self._executed_request_ids: Set[str] = set()
        self._unknown_request_ids: Set[str] = set()
        self._executed_job_ids: Dict[str, str] = {}
        self._unknown_job_ids: Dict[str, str] = {}
        self._in_flight_request_ids: Set[str] = set()
        self.authorization_registry = InMemoryAuthorizationConsumptionRegistry()

    def is_executed(self, request_id: str) -> bool:
        return request_id in self._executed_request_ids

    def mark_executed(
        self, request_id: str, executed_at: Optional[str] = None, job_id: Optional[str] = None
    ) -> None:
        job_id = _merge_job_id(
            self._executed_job_ids.get(request_id), _checked_job_id(job_id), request_id
        )
        self._executed_request_ids.add(request_id)
        if job_id is not None:
            self._executed_job_ids[request_id] = job_id
        if request_id in self._in_flight_request_ids:
            self._in_flight_request_ids.discard(request_id)
            self._unknown_request_ids.discard(request_id)

    @contextmanager
    def in_flight(self, request_id: str) -> Iterator[None]:
        """Phase P3.91 — cf. `FileExecutedRequestStore.in_flight()`."""

        if request_id in self._executed_request_ids or request_id in self._unknown_request_ids:
            raise ExecutedRequestStoreConflictError(
                f"Request '{request_id}' is already recorded; refusing to "
                f"mark a new in-flight attempt."
            )
        self._unknown_request_ids.add(request_id)
        self._in_flight_request_ids.add(request_id)
        try:
            yield
        except HiggsfieldRealGenerationDisabledError:
            if request_id in self._in_flight_request_ids:
                self._in_flight_request_ids.discard(request_id)
                self._unknown_request_ids.discard(request_id)
            raise

    def recorded_job_id(self, request_id: str) -> Optional[str]:
        """Phase P3.89 — `job_id` enregistré pour CE `request_id`
        (exécuté en priorité, sinon UNKNOWN), ou `None`. Trace
        uniquement, jamais une autorisation."""

        return self._executed_job_ids.get(request_id) or self._unknown_job_ids.get(request_id)

    def is_unknown(self, request_id: str) -> bool:
        """
        Phase P2.20 : `True` si une tentative de `create_job()` a eu
        lieu pour cette requête mais que son enregistrement fiable
        (`mark_executed`) a échoué -- état FAIL CLOSED, jamais
        rejouable automatiquement.
        """

        return request_id in self._unknown_request_ids

    def mark_unknown(self, request_id: str, reason: str = "", job_id: Optional[str] = None) -> None:
        job_id = _merge_job_id(
            self._unknown_job_ids.get(request_id), _unknown_job_id(job_id), request_id
        )
        self._unknown_request_ids.add(request_id)
        self._in_flight_request_ids.discard(request_id)
        if job_id is not None:
            self._unknown_job_ids[request_id] = job_id


class FileExecutedRequestStore:
    """
    Persistance JSON locale du replay guard, survit à un redémarrage
    du processus. Utilisée par le chemin de production réel
    (director.py::AIDirector._build_default_report_service()).

    Format du fichier :
        {"executed_requests": {"<request_id>": {"executed_at": "<iso8601>",
                                                "job_id": "<id>"}}}
    (`job_id` : Phase P3.89, absent des enregistrements antérieurs --
    toujours lus normalement.)

    Écriture atomique : fichier temporaire dans le même répertoire
    (garantit un `os.replace` atomique sur le même volume, POSIX et
    Windows) puis renommage — jamais de fichier tronqué visible par un
    lecteur concurrent, même en cas de crash pendant l'écriture.
    """

    def __init__(self, path: Path, lock_timeout_seconds: float = 10.0) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.lock_timeout_seconds = lock_timeout_seconds
        # Phase B : registre de consommation SÉPARÉ, même dossier d'état,
        # fichier et verrou propres (jamais `executed_requests.json`).
        self.authorization_registry = FileAuthorizationConsumptionRegistry(
            self.path.with_name(CONSUMED_AUTHORIZATIONS_FILENAME),
            lock_timeout_seconds=lock_timeout_seconds,
        )

    @contextmanager
    def _locked(self, context: str, write: bool = False) -> Iterator[None]:
        """
        Phase P3.91 — verrou global du fichier (cf. docstring du
        module). Une lecture sans répertoire parent n'a aucun état à
        protéger et ne crée jamais ce répertoire.
        """

        if not write and not self.path.parent.exists():
            yield
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):
                # PermissionError : Windows, verrou en cours de suppression.
                if time.monotonic() >= deadline:
                    raise ExecutedRequestStoreLockTimeoutError(
                        f"[{context}] Replay guard lock '{self.lock_path}' could "
                        f"not be acquired within {self.lock_timeout_seconds}s "
                        f"(holder: {self._lock_holder()}) -- failing closed. An "
                        f"orphaned lock is never removed automatically; human "
                        f"review required."
                    ) from None
                time.sleep(0.005)

        # Phase P3.102 (F5) : le fd reste ouvert pendant TOUTE la section
        # critique, fermé seulement à la libération -- comme
        # `critical_section_lock.py`.
        # Sous Windows, un fichier ouvert par `os.open` ne peut pas être
        # supprimé par un autre processus (WinError 32) : fermé avant le
        # `yield`, le verrou pouvait être supprimé pendant qu'il était
        # détenu, un second processus entrait alors dans la section
        # critique (mise à jour perdue du registre anti-rejeu).
        try:
            os.write(fd, json.dumps({
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8"))
            yield
        finally:
            try:
                os.close(fd)
            finally:
                release_deadline = time.monotonic() + _LOCK_RELEASE_RETRY_SECONDS
                while True:
                    try:
                        self.lock_path.unlink()
                    except PermissionError:
                        # Phase P3.98 (D3) : sous Windows, un lecteur du verrou
                        # (`_lock_holder()` d'un autre processus) fait échouer
                        # la suppression ; abandonner aussitôt laissait orphelin
                        # un verrou libéré proprement. Nouvel essai, borné --
                        # ensuite comportement inchangé (verrou laissé : fail
                        # closed, jamais supprimé automatiquement ailleurs).
                        if time.monotonic() < release_deadline:
                            time.sleep(_LOCK_RELEASE_RETRY_INTERVAL_SECONDS)
                            continue
                    except OSError:
                        pass
                    break

    def _lock_holder(self) -> str:
        try:
            return self.lock_path.read_text(encoding="utf-8")[:200] or "<empty>"
        except OSError:
            return "<unreadable>"

    def is_executed(self, request_id: str) -> bool:
        with self._locked(context="is_executed"):
            if not self.path.exists():
                # Absence légitime : aucune exécution n'a encore eu lieu.
                # Ce n'est PAS une corruption.
                return False

            data = self._read_full(context="is_executed")
            return request_id in data["executed_requests"]

    def is_unknown(self, request_id: str) -> bool:
        """
        Phase P2.20 : `True` si une tentative de `create_job()` a eu
        lieu pour cette requête mais que son enregistrement fiable
        (`mark_executed`) a échoué -- état FAIL CLOSED, jamais
        rejouable automatiquement (cf. GenerationApprovalGate.
        evaluate(), GenerationApprovalDecision.EXECUTION_STATE_UNKNOWN).
        """

        with self._locked(context="is_unknown"):
            if not self.path.exists():
                return False

            data = self._read_full(context="is_unknown")
            return request_id in data["unknown_requests"]

    def mark_executed(
        self, request_id: str, executed_at: Optional[str] = None, job_id: Optional[str] = None
    ) -> None:
        """
        Enregistre une exécution réellement survenue. Refuse
        volontairement d'écraser silencieusement un état existant
        illisible : une corruption découverte ici est signalée
        (levée), jamais masquée par un simple redémarrage à vide du
        registre — cf. limites connues dans le docstring du module.

        Phase P3.89 : `job_id`, s'il est fourni, est écrit dans le même
        enregistrement (même écriture atomique).
        """

        job_id = _checked_job_id(job_id)
        executed_at = executed_at or datetime.now(timezone.utc).isoformat()

        with self._locked(context="mark_executed", write=True):
            data = self._read_full_or_empty(context="mark_executed")
            previous = self._record_job_id(data, "executed_requests", request_id, "mark_executed")
            job_id = _merge_job_id(previous, job_id, request_id)
            record: Dict[str, Any] = {"executed_at": executed_at}
            if job_id is not None:
                record["job_id"] = job_id
            data["executed_requests"][request_id] = record
            # Phase P3.91 : le marqueur write-ahead est retiré DANS la
            # même écriture atomique -- jamais un UNKNOWN ordinaire.
            if self._is_in_flight_record(data["unknown_requests"].get(request_id)):
                del data["unknown_requests"][request_id]
            self._write_full(data)

    @contextmanager
    def in_flight(self, request_id: str) -> Iterator[None]:
        """
        Phase P3.91 — write-ahead autour de `create_job()`. À l'entrée :
        persiste un enregistrement `unknown_requests` marqué
        `in_flight`, lu comme UNKNOWN par `is_unknown()` ; refuse
        (`ExecutedRequestStoreConflictError`) si la requête est déjà
        enregistrée (exécutée, UNKNOWN, ou marqueur d'une tentative
        précédente) -- jamais un écrasement. Ce marqueur est donc
        toujours CELUI de ce bloc.

        Unique retour arrière : `HiggsfieldRealGenerationDisabledError`
        levée DANS le bloc (le Provider réel la lève avant tout appel
        client : aucun job n'a pu exister). Le marqueur de CE bloc est
        alors retiré et, si le fichier n'existait pas à l'entrée, son
        absence est restaurée. Toute autre sortie (exception, crash,
        sortie normale sans `mark_executed()`) laisse le marqueur.
        Aucune méthode publique ne retire un UNKNOWN existant
        (invariant P3.38).
        """

        created = self._begin_in_flight(request_id)
        try:
            yield
        except HiggsfieldRealGenerationDisabledError as refusal:
            try:
                self._rollback_own_in_flight(request_id, created)
            except Exception as rollback_error:
                # Plus restrictif : la requête reste UNKNOWN, et le
                # refus d'origine se propage intact.
                refusal.add_note(
                    f"P3.91: in-flight rollback failed ({rollback_error!r}); "
                    f"request '{request_id}' remains EXECUTION_STATE_UNKNOWN."
                )
            raise

    def _begin_in_flight(self, request_id: str) -> bool:
        with self._locked(context="in_flight", write=True):
            created = not self.path.exists()
            data = self._read_full_or_empty(context="in_flight")
            if request_id in data["executed_requests"] or request_id in data["unknown_requests"]:
                raise ExecutedRequestStoreConflictError(
                    f"Request '{request_id}' is already recorded; refusing to "
                    f"mark a new in-flight attempt."
                )
            data["unknown_requests"][request_id] = {
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "reason": (
                    "in-flight: create_job() attempt started; no confirmed "
                    "outcome recorded (write-ahead, P3.91)"
                ),
                "in_flight": True,
            }
            self._write_full(data)
            return created

    def _rollback_own_in_flight(self, request_id: str, created: bool) -> None:
        with self._locked(context="in_flight_rollback", write=True):
            data = self._read_full(context="in_flight_rollback")
            if request_id in data["executed_requests"] or not self._is_in_flight_record(
                data["unknown_requests"].get(request_id)
            ):
                raise ExecutedRequestStoreConflictError(
                    f"Request '{request_id}' no longer carries this block's "
                    f"in-flight marker; refusing to alter it."
                )
            del data["unknown_requests"][request_id]
            if created and set(data) == {"executed_requests", "unknown_requests"} and not (
                data["executed_requests"] or data["unknown_requests"]
            ):
                self.path.unlink()
            else:
                self._write_full(data)

    @staticmethod
    def _is_in_flight_record(record: Any) -> bool:
        return isinstance(record, dict) and record.get("in_flight") is True

    def recorded_job_id(self, request_id: str) -> Optional[str]:
        """
        Phase P3.89 — `job_id` enregistré pour CE `request_id`
        (enregistrement "executed" en priorité, sinon "unknown"), ou
        `None` si aucun. Lecture seule, fail closed sur un état
        illisible ou un champ `job_id` mal formé. Trace uniquement :
        jamais consulté par `GenerationApprovalGate.evaluate()`.
        """

        with self._locked(context="recorded_job_id"):
            if not self.path.exists():
                return None

            data = self._read_full(context="recorded_job_id")
            return self._record_job_id(
                data, "executed_requests", request_id, "recorded_job_id"
            ) or self._record_job_id(data, "unknown_requests", request_id, "recorded_job_id")

    def _record_job_id(
        self, data: Dict[str, Any], registry: str, request_id: str, context: str
    ) -> Optional[str]:
        record = data[registry].get(request_id)
        if record is None:
            return None
        job_id = record.get("job_id") if isinstance(record, dict) else None
        if not isinstance(record, dict) or (
            job_id is not None and (not isinstance(job_id, str) or not job_id)
        ):
            raise ExecutedRequestStoreCorruptedError(
                f"[{context}] Replay guard state at '{self.path}' has a "
                f"malformed '{registry}' record for request '{request_id}'."
            )
        return job_id

    def mark_unknown(
        self,
        request_id: str,
        reason: str = "",
        marked_at: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> None:
        """
        Phase P2.20 : enregistre qu'une tentative de `create_job()` a
        eu lieu pour cette requête mais que `mark_executed()` a
        échoué juste après -- l'état réel (job créé ou non côté
        Higgsfield) reste INCONNU de ce module, qui ne fait que
        consigner le FAIT que cette ambiguïté existe, pour bloquer
        tout rejeu automatique futur. Écriture atomique, comme
        `mark_executed()`. Une corruption découverte ici est levée,
        jamais masquée.
        """

        job_id = _unknown_job_id(job_id)
        marked_at = marked_at or datetime.now(timezone.utc).isoformat()

        with self._locked(context="mark_unknown", write=True):
            data = self._read_full_or_empty(context="mark_unknown")
            previous = self._record_job_id(data, "unknown_requests", request_id, "mark_unknown")
            job_id = _merge_job_id(previous, job_id, request_id)
            # Reconstruit sans `in_flight` : un marqueur write-ahead
            # devient ici un UNKNOWN ordinaire (P3.91).
            record: Dict[str, Any] = {"marked_at": marked_at, "reason": reason}
            if job_id is not None:
                record["job_id"] = job_id
            data["unknown_requests"][request_id] = record
            self._write_full(data)

    def _read_full_or_empty(self, context: str) -> Dict[str, Any]:
        if not self.path.exists():
            return {"executed_requests": {}, "unknown_requests": {}}
        return self._read_full(context=context)

    def _read_full(self, context: str) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise ExecutedRequestStoreCorruptedError(
                f"[{context}] Replay guard state at '{self.path}' could not "
                f"be read: {error}"
            ) from error

        if not isinstance(data, dict) or not isinstance(
            data.get("executed_requests"), dict
        ):
            raise ExecutedRequestStoreCorruptedError(
                f"[{context}] Replay guard state at '{self.path}' has an "
                f"unexpected shape (expected "
                f'{{"executed_requests": {{...}}}}).'
            )

        # `unknown_requests` (Phase P2.20) est OPTIONNEL pour la
        # compatibilité avec un état écrit par une version antérieure
        # à P2.20 (P2.15) : absent -> traité comme vide, jamais comme
        # une corruption. Présent mais mal formé -> corruption réelle.
        unknown_requests = data.get("unknown_requests", {})
        if not isinstance(unknown_requests, dict):
            raise ExecutedRequestStoreCorruptedError(
                f"[{context}] Replay guard state at '{self.path}' has an "
                f"unexpected shape for 'unknown_requests' (expected an "
                f"object)."
            )

        data["unknown_requests"] = unknown_requests
        return data

    def _write_full(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".tmp-executed-requests-",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            # Phase P3.91 : BaseException (KeyboardInterrupt/SystemExit
            # inclus) -- P3.90 C4 laissait sinon un fichier temporaire.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ----------------------------------------------------------------------
# Phase B — registre de consommation des autorisations (cf. docstring
# de module). Séparé de `executed_requests.json` (invariant P3.89).
# ----------------------------------------------------------------------

CONSUMED_AUTHORIZATIONS_FILENAME = "consumed_authorizations.json"
_CONSUMED_REGISTRY_KEY = "consumed_authorization_sha256"
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")


def authorization_id_sha256(authorization_id: str) -> str:
    """Condensat SHA-256 (hex) d'un `authorization_id` validé : seule
    forme jamais persistée de l'identifiant."""

    return hashlib.sha256(validate_authorization_id(authorization_id).encode("utf-8")).hexdigest()


def _checked_consumer_request_id(request_id: Any) -> str:
    if not isinstance(request_id, str) or not request_id:
        raise ValueError(f"request_id must be a non-empty str, got {request_id!r}")
    return request_id


def _already_consumed(digest: str) -> AuthorizationAlreadyConsumedError:
    return AuthorizationAlreadyConsumedError(
        f"Authorization (sha256 {digest}) has already been consumed by a "
        f"prior execution attempt; a new explicit human authorization is "
        f"required."
    )


class InMemoryAuthorizationConsumptionRegistry:
    """
    Registre de consommation EN MÉMOIRE : sûr entre threads d'un même
    processus (vérification + inscription sous un verrou), mais AUCUNE
    persistance -- tout est oublié au redémarrage. Réservé aux tests
    mock-only et au store en mémoire ; jamais une garantie durable.
    """

    def __init__(self) -> None:
        self._consumed: Dict[str, Dict[str, str]] = {}
        self._guard = threading.Lock()

    def is_consumed(self, authorization_id: str) -> bool:
        digest = authorization_id_sha256(authorization_id)
        with self._guard:
            return digest in self._consumed

    def consume(self, authorization_id: str, request_id: str) -> None:
        digest = authorization_id_sha256(authorization_id)
        request_id = _checked_consumer_request_id(request_id)
        with self._guard:
            if digest in self._consumed:
                raise _already_consumed(digest)
            self._consumed[digest] = {
                "request_id": request_id,
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            }


class FileAuthorizationConsumptionRegistry:
    """
    Registre de consommation PERSISTANT, local à une machine et au
    dossier d'état partagé. Format :
        {"consumed_authorization_sha256": {"<sha256 hex>":
            {"request_id": "<id>", "consumed_at": "<iso8601>"}}}
    Verrou propre (`<path>.lock`, création exclusive, descripteur gardé
    ouvert pendant toute la section, attente bornée puis
    `AuthorizationRegistryLockTimeoutError`, verrou orphelin jamais
    supprimé automatiquement). Aucune méthode de retrait ni de purge.
    """

    def __init__(self, path: Path, lock_timeout_seconds: float = 10.0) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.lock_timeout_seconds = lock_timeout_seconds

    def is_consumed(self, authorization_id: str) -> bool:
        """Lecture seule. Registre absent -> `False` sans rien créer ni
        verrouiller (le dossier d'état n'est jamais touché) ; présent ->
        lecture sous verrou, fail closed sur tout état illisible."""

        digest = authorization_id_sha256(authorization_id)
        if not self.path.exists():
            return False
        with self._locked(context="is_consumed"):
            return digest in self._read_or_empty(context="is_consumed")[_CONSUMED_REGISTRY_KEY]

    def consume(self, authorization_id: str, request_id: str) -> None:
        """Vérifie PUIS inscrit, dans une seule écriture atomique sous le
        verrou du registre. Déjà consommée -> `AuthorizationAlreadyConsumed
        Error` sans rien écrire. Toute autre erreur (corruption, verrou,
        écriture) se propage : l'appelant ne doit jamais poursuivre."""

        digest = authorization_id_sha256(authorization_id)
        request_id = _checked_consumer_request_id(request_id)
        with self._locked(context="consume"):
            data = self._read_or_empty(context="consume")
            consumed = data[_CONSUMED_REGISTRY_KEY]
            if digest in consumed:
                raise _already_consumed(digest)
            consumed[digest] = {
                "request_id": request_id,
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write(data)

    @contextmanager
    def _locked(self, context: str) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):
                if time.monotonic() >= deadline:
                    raise AuthorizationRegistryLockTimeoutError(
                        f"[{context}] Authorization consumption registry lock "
                        f"'{self.lock_path}' could not be acquired within "
                        f"{self.lock_timeout_seconds}s -- failing closed. An "
                        f"orphaned lock is never removed automatically; human "
                        f"review required."
                    ) from None
                time.sleep(0.005)

        try:
            os.write(fd, json.dumps({
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8"))
            yield
        finally:
            try:
                os.close(fd)
            finally:
                release_deadline = time.monotonic() + _LOCK_RELEASE_RETRY_SECONDS
                while True:
                    try:
                        self.lock_path.unlink()
                    except PermissionError:
                        if time.monotonic() < release_deadline:
                            time.sleep(_LOCK_RELEASE_RETRY_INTERVAL_SECONDS)
                            continue
                    except OSError:
                        pass
                    break

    def _read_or_empty(self, context: str) -> Dict[str, Any]:
        if not self.path.exists():
            return {_CONSUMED_REGISTRY_KEY: {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise AuthorizationRegistryCorruptedError(
                f"[{context}] Authorization consumption registry at "
                f"'{self.path}' could not be read: {error}"
            ) from error

        consumed = data.get(_CONSUMED_REGISTRY_KEY) if isinstance(data, dict) else None
        if not isinstance(consumed, dict) or any(
            not isinstance(digest, str)
            or not _SHA256_HEX_PATTERN.fullmatch(digest)
            or not isinstance(record, dict)
            or not isinstance(record.get("request_id"), str)
            or not isinstance(record.get("consumed_at"), str)
            for digest, record in consumed.items()
        ):
            raise AuthorizationRegistryCorruptedError(
                f"[{context}] Authorization consumption registry at "
                f"'{self.path}' has an unexpected shape -- failing closed."
            )
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=".tmp-consumed-authorizations-",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
