"""Mock-only check that a run's GitHub account and its approver are separate.

The check relies on an injected registry: an administrator's closed-world
attestation that maps numeric GitHub account IDs and approver IDs to
principals. Any unknown, revoked or inconsistent entry is refused.

A successful result is an account separation attested by the administrator.
It does not prove that two different people are involved, and it does not
resolve G1 D-5. Only the OIDC ``actor_id`` is used; the renamable ``actor``
login never takes part in the decision. This module performs no storage,
network access or approval decision and is not wired to any caller yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, ClassVar, Protocol, TypeVar

# Same assumption as the OIDC verifier: a positive decimal string without a
# leading zero (GitHub's official example is "12").
_ACCOUNT_ID = re.compile(r"^[1-9][0-9]*$")
# Same format as the approval statement's approver_id.
_REGISTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

_Entry = TypeVar("_Entry")


class AccountSeparationError(ValueError):
    """Generic refusal; messages never include account, approver or principal IDs."""


def _require_id(name: str, value: object, pattern: re.Pattern[str]) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} is missing or malformed")


def _require_revoked_flag(value: object) -> None:
    if type(value) is not bool:
        raise ValueError("revoked must be a boolean")


@dataclass(frozen=True, slots=True)
class AccountBinding:
    """Registry entry: one GitHub account ID attested to belong to a principal."""

    account_id: str
    principal_id: str
    revoked: bool

    def __post_init__(self) -> None:
        _require_id("account_id", self.account_id, _ACCOUNT_ID)
        _require_id("principal_id", self.principal_id, _REGISTRY_ID)
        _require_revoked_flag(self.revoked)


@dataclass(frozen=True, slots=True)
class ApproverBinding:
    """Registry entry: one approver ID attested to belong to a principal."""

    approver_id: str
    principal_id: str
    revoked: bool

    def __post_init__(self) -> None:
        _require_id("approver_id", self.approver_id, _REGISTRY_ID)
        _require_id("principal_id", self.principal_id, _REGISTRY_ID)
        _require_revoked_flag(self.revoked)


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    """Registry entry: a principal, the administrator's stand-in for one person."""

    principal_id: str
    revoked: bool

    def __post_init__(self) -> None:
        _require_id("principal_id", self.principal_id, _REGISTRY_ID)
        _require_revoked_flag(self.revoked)


class SeparationRegistry(Protocol):
    """Administrator-maintained, closed-world registry of accounts and approvers."""

    def resolve_account(self, account_id: str) -> AccountBinding:
        """Return the binding of a GitHub account ID or raise ``KeyError``."""

    def resolve_approver(self, approver_id: str) -> ApproverBinding:
        """Return the binding of an approver ID or raise ``KeyError``."""

    def resolve_principal(self, principal_id: str) -> PrincipalRecord:
        """Return a principal or raise ``KeyError``."""


@dataclass(frozen=True, slots=True)
class AdminAttestedAccountSeparation:
    """The run account and the approver belong to distinct registry principals.

    This rests on the administrator's attestation only. It does not prove
    that two different people are involved and does not resolve G1 D-5.
    """

    actor_principal_id: str
    approver_principal_id: str
    evidence: str = "ADMIN_ATTESTED_ACCOUNT_SEPARATION"

    EVIDENCE: ClassVar[str] = "ADMIN_ATTESTED_ACCOUNT_SEPARATION"

    def __post_init__(self) -> None:
        _require_id("actor_principal_id", self.actor_principal_id, _REGISTRY_ID)
        _require_id("approver_principal_id", self.approver_principal_id, _REGISTRY_ID)
        if self.actor_principal_id == self.approver_principal_id:
            raise ValueError("principals must be distinct")
        if self.evidence != self.EVIDENCE:
            raise ValueError("evidence must name the administrator attestation")


class AccountSeparationChecker:
    """Check administrator-attested account separation without side effects."""

    def __init__(self, registry: SeparationRegistry) -> None:
        for method in ("resolve_account", "resolve_approver", "resolve_principal"):
            if not callable(getattr(registry, method, None)):
                raise TypeError(f"registry must provide {method}()")
        self._registry = registry

    def check(self, actor_id: str, approver_id: str) -> AdminAttestedAccountSeparation:
        """Refuse unless ``actor_id`` and ``approver_id`` map to distinct active principals."""

        if type(actor_id) is not str or _ACCOUNT_ID.fullmatch(actor_id) is None:
            raise AccountSeparationError("run actor ID is missing or malformed")
        if type(approver_id) is not str or _REGISTRY_ID.fullmatch(approver_id) is None:
            raise AccountSeparationError("approver ID is missing or malformed")

        account = self._lookup(self._registry.resolve_account, actor_id, AccountBinding, "run account")
        if account.account_id != actor_id:
            raise AccountSeparationError("registry entry is inconsistent")
        if account.revoked:
            raise AccountSeparationError("run account is revoked")

        approver = self._lookup(self._registry.resolve_approver, approver_id, ApproverBinding, "approver")
        if approver.approver_id != approver_id:
            raise AccountSeparationError("registry entry is inconsistent")
        if approver.revoked:
            raise AccountSeparationError("approver is revoked")

        for principal_id, role in ((account.principal_id, "run account"), (approver.principal_id, "approver")):
            principal = self._lookup(self._registry.resolve_principal, principal_id, PrincipalRecord, None)
            if principal.principal_id != principal_id:
                raise AccountSeparationError("registry entry is inconsistent")
            if principal.revoked:
                raise AccountSeparationError(f"{role} principal is revoked")

        if account.principal_id == approver.principal_id:
            raise AccountSeparationError("run account and approver belong to the same principal")
        return AdminAttestedAccountSeparation(
            actor_principal_id=account.principal_id,
            approver_principal_id=approver.principal_id,
        )

    @staticmethod
    def _lookup(
        resolve: Callable[[str], object],
        key: str,
        expected: type[_Entry],
        role: str | None,
    ) -> _Entry:
        """Resolve one entry; ``role`` is None when absence means inconsistency."""

        try:
            entry = resolve(key)
        except KeyError:
            if role is None:
                # A binding that names an unknown principal.
                raise AccountSeparationError("registry entry is inconsistent") from None
            raise AccountSeparationError(f"{role} is not registered") from None
        except Exception:
            # Registry implementations must fail closed; their errors may
            # carry identifiers, so they are never chained or echoed.
            raise AccountSeparationError("registry could not be read") from None
        if type(entry) is not expected:
            raise AccountSeparationError("registry entry is inconsistent")
        return entry
