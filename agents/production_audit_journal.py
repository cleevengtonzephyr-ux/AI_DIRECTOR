"""
AI DIRECTOR — Journal d'audit de production (Phase F, condition 5)

Fichier JSON Lines chaîné (option J-b de la Phase E), écrit uniquement par
ajout en fin de fichier : chaque entrée porte l'empreinte de la précédente.
Un fichier de tête voisin (`<journal>.head`) enregistre le numéro et
l'empreinte de la dernière entrée ; il est réécrit après chaque ajout.

Ce qui est DÉTECTÉ (vérification locale) :
- modification d'une entrée, suppression ou insertion au début ou au
  milieu (chaîne rompue) ;
- suppression des dernières entrées, ou troncature à vide : la fin de la
  chaîne ne correspond plus à la tête ;
- suppression du seul journal ou de la seule tête.

Ce qui n'est PAS détecté : la suppression conjointe du journal et de sa
tête (état « absent », voir plus bas), ni une réécriture complète et
cohérente du journal et de la tête. Il n'y a ni clé, ni ancre externe
(option J-c, non mise en œuvre) : ce journal n'est pas inviolable, il
rend visibles certaines altérations locales. Le système de fichiers
n'interdit pas non plus d'écrire ailleurs qu'en fin de fichier.

État absent : ni journal ni tête. Ce n'est JAMAIS lu comme un journal
vide et intact : `entries()`, `verify()` et `append()` lèvent
`AuditJournalMissingError`. Seul `initialize()`, appelé explicitement,
crée un journal neuf (et refuse s'il en existe déjà un, même partiel).

Échec fermé :
- chaîne rompue, tête discordante, ligne illisible, fichier inaccessible
  ou journal absent -> `verify()` et `append()` lèvent, et rien n'est
  écrit. Un arrêt brutal entre l'ajout d'une entrée et la mise à jour de
  la tête laisse un journal discordant : il est alors refusé, et un
  rapprochement humain est requis ;
- un détail qui ressemble à un secret, à un jeton, à un en-tête
  d'authentification ou à une URL (signée ou de résultat) est refusé :
  le journal ne contient que des identifiants, des empreintes, des
  décisions et des dates.

Le journal trace, il ne décide jamais : aucune lecture du journal ne vaut
autorisation. Un seul écrivain à la fois est supposé (groupe de
concurrence du workflow) ; un entrelacement serait détecté à la
vérification suivante, pas empêché.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping


GENESIS_SHA256 = "0" * 64

AUDIT_EVENTS = frozenset(
    {
        "manifest_prepared",
        "manifest_verified",
        "manifest_mismatch",
        "execution_refused",
        "submission_refused_provider_closed",
        "submit_attempt",
        "submit_outcome",
        "status_observed",
        "cancel_requested",
        "cancel_outcome",
        "execution_state_unknown",
    }
)

_FORBIDDEN_KEY_FRAGMENTS = (
    "secret", "token", "authorization", "password", "credential", "api_key",
    "apikey", "signature", "url", "cookie", "prompt",
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"://"),
    re.compile(r"\b(?:key|bearer|basic)\s+\S+:\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+\S{8,}", re.IGNORECASE),
    re.compile(r"x-amz-|signature=|sig=|token=", re.IGNORECASE),
)
_PLAIN_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MAX_STRING = 256


class AuditJournalError(RuntimeError):
    """Écriture refusée ou impossible : l'action tracée ne doit pas avoir lieu."""


class AuditJournalCorruptedError(AuditJournalError):
    """Chaîne rompue, tête discordante, entrée illisible ou fichier partiellement supprimé."""


class AuditJournalMissingError(AuditJournalError):
    """Ni journal ni tête : état absent, jamais confondu avec un journal vide."""


def _check_value(path: str, value: Any) -> None:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, str):
        if len(value) > _MAX_STRING or any(ord(ch) < 0x20 for ch in value):
            raise AuditJournalError(f"audit detail {path!r} is too long or contains control characters")
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise AuditJournalError(f"audit detail {path!r} looks like a URL or a credential: refused")
        return
    raise AuditJournalError(f"audit detail {path!r} has unsupported type {type(value).__name__}")


def _check_details(details: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(details, Mapping):
        raise AuditJournalError("audit details must be a mapping")
    checked = {}
    for key, value in details.items():
        if not isinstance(key, str) or not _PLAIN_KEY.fullmatch(key):
            raise AuditJournalError(f"audit detail key {key!r} is not a plain identifier")
        if any(fragment in key for fragment in _FORBIDDEN_KEY_FRAGMENTS):
            raise AuditJournalError(f"audit detail key {key!r} names forbidden content: refused")
        _check_value(key, value)
        checked[key] = value
    return checked


def _entry_digest(entry_without_digest: Dict[str, Any]) -> str:
    canonical = json.dumps(entry_without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditJournal:
    def __init__(self, path: Path, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.path = Path(path)
        self.head_path = self.path.with_name(self.path.name + ".head")
        self._clock = clock

    def is_absent(self) -> bool:
        """Vrai seulement si NI le journal NI sa tête n'existent."""

        return not self.path.exists() and not self.head_path.exists()

    def initialize(self) -> None:
        """Crée un journal neuf et vide. Refuse si le journal ou sa tête existe déjà."""

        if not self.is_absent():
            raise AuditJournalError("audit journal already exists (or partially exists): not reinitialized")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            os.close(descriptor)
        except OSError as error:
            raise AuditJournalError(f"audit journal creation failed ({type(error).__name__})") from error
        self._write_head(0, GENESIS_SHA256)

    def _write_head(self, seq: int, entry_sha256: str) -> None:
        data = json.dumps({"seq": seq, "entry_sha256": entry_sha256}, sort_keys=True).encode("utf-8")
        temporary = self.head_path.with_name(self.head_path.name + ".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
            try:
                os.write(descriptor, data)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, self.head_path)
        except OSError as error:
            raise AuditJournalError(f"audit journal head write failed ({type(error).__name__})") from error

    def _read_head(self) -> Dict[str, Any]:
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise AuditJournalCorruptedError(f"audit journal head unreadable ({type(error).__name__})") from None
        if (
            not isinstance(head, dict)
            or set(head) != {"seq", "entry_sha256"}
            or isinstance(head["seq"], bool)
            or not isinstance(head["seq"], int)
            or not isinstance(head["entry_sha256"], str)
        ):
            raise AuditJournalCorruptedError("audit journal head is malformed")
        return head

    def entries(self) -> List[Dict[str, Any]]:
        """Toutes les entrées, chaîne et fin de chaîne vérifiées. Absent : `AuditJournalMissingError`."""

        journal_exists, head_exists = self.path.exists(), self.head_path.exists()
        if not journal_exists and not head_exists:
            raise AuditJournalMissingError("audit journal is absent: call initialize() explicitly to start a new one")
        if not journal_exists:
            raise AuditJournalCorruptedError("audit journal file was deleted but its head remains")
        if not head_exists:
            raise AuditJournalCorruptedError("audit journal head is missing: the end of the chain cannot be checked")
        head = self._read_head()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise AuditJournalCorruptedError(f"audit journal unreadable ({type(error).__name__})") from error
        previous = GENESIS_SHA256
        entries = []
        for index, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
            except ValueError:
                raise AuditJournalCorruptedError(f"audit journal line {index} is not JSON") from None
            if not isinstance(entry, dict) or entry.get("seq") != index or entry.get("prev_sha256") != previous:
                raise AuditJournalCorruptedError(f"audit journal chain broken at line {index}")
            claimed = entry.get("entry_sha256")
            if claimed != _entry_digest({k: v for k, v in entry.items() if k != "entry_sha256"}):
                raise AuditJournalCorruptedError(f"audit journal entry {index} was modified")
            previous = claimed
            entries.append(entry)
        if head["seq"] != len(entries) or head["entry_sha256"] != previous:
            raise AuditJournalCorruptedError(
                f"audit journal end of chain (entry {len(entries)}) does not match its head (entry {head['seq']}): "
                "trailing entries were removed, or an append was interrupted"
            )
        return entries

    def verify(self) -> int:
        return len(self.entries())

    def append(self, event: str, request_id: str, details: Mapping[str, Any]) -> str:
        if event not in AUDIT_EVENTS:
            raise AuditJournalError(f"unknown audit event {event!r}")
        _check_value("request_id", request_id)
        if not isinstance(request_id, str) or not request_id:
            raise AuditJournalError("request_id is required")
        checked = _check_details(details)
        existing = self.entries()
        entry = {
            "seq": len(existing) + 1,
            "at": self._clock().isoformat(),
            "event": event,
            "request_id": request_id,
            "details": checked,
            "prev_sha256": existing[-1]["entry_sha256"] if existing else GENESIS_SHA256,
        }
        entry["entry_sha256"] = _entry_digest(entry)
        line = (json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        try:
            # Sans O_CREAT : le journal a été vérifié présent ci-dessus.
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0))
            try:
                os.write(descriptor, line)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise AuditJournalError(f"audit journal write failed ({type(error).__name__})") from error
        self._write_head(entry["seq"], entry["entry_sha256"])
        return entry["entry_sha256"]
