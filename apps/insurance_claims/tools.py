from typing import Protocol

from .database import AccessDenied, Claim, ClaimFilters
from .identity import VerifiedIdentity
from .sop import Phase, WorkflowState


class ClaimRepository(Protocol):
    def owns(self, identity: VerifiedIdentity, case_id: str) -> bool: ...
    def list_owned(self, identity: VerifiedIdentity | None, filters: ClaimFilters) -> list[Claim]: ...
    def get_owned(self, identity: VerifiedIdentity | None, case_id: str) -> Claim: ...


class ClaimToolGateway:
    def __init__(self, claims: ClaimRepository):
        self._claims = claims

    @staticmethod
    def _authorize(state: WorkflowState) -> VerifiedIdentity:
        if not isinstance(state.identity, VerifiedIdentity) or state.phase not in {
            Phase.RESOLVE_INTENT, Phase.PROCESS_CASE, Phase.POST_PROCESS
        }:
            raise AccessDenied("Claim access denied")
        return state.identity

    def search_claims(
        self, state: WorkflowState, filters: ClaimFilters = ClaimFilters()
    ) -> list[Claim]:
        return self._claims.list_owned(self._authorize(state), filters)

    def get_claim(self, state: WorkflowState, case_id: str) -> Claim:
        identity = self.check_ownership(state, case_id)
        return self._claims.get_owned(identity, case_id)

    def check_ownership(self, state: WorkflowState, case_id: str) -> VerifiedIdentity:
        identity = self._authorize(state)
        if not self._claims.owns(identity, case_id):
            raise AccessDenied("Claim access denied")
        return identity
