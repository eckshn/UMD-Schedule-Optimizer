"""Which degree programs count each course, shared by course selection and the degree audit."""

from typing import Dict, List, Mapping, Optional, Tuple

from ..models.catalog import Catalog
from ..models.student import RequirementOwner
from . import rules


class ClaimLedger:
    """
    The programs (majors, minors) each course counts toward.

    A course counts toward one requirement per program. It may also count
    toward another program when ``rules.may_share`` allows it for every
    program already counting it (majors share with majors; a minor shares with
    majors, never with another minor), as long as the courses that program
    shares stay within ``rules.within_overlap_limit``. Works for any number of
    majors and minors. Courses that only "degree" requirements use (gen-eds,
    credit minimums) are never claimed. Equivalent courses (``Catalog.equivalents``:
    honors/base, cross-listed such as CMSC460/AMSC460) are one course here.
    """

    def __init__(self, catalog: Catalog,
                 owners: Optional[Mapping[str, List[RequirementOwner]]] = None,
                 shares: Optional[Mapping[RequirementOwner, List[str]]] = None,
                 codes: Optional[Mapping[str, str]] = None):
        self.catalog = catalog
        # keyed by _key(code): the programs counting the course, and the code first claimed
        self.owners: Dict[str, List[RequirementOwner]] = {
            key: list(held) for key, held in (owners or {}).items()}
        self.codes: Dict[str, str] = dict(codes or {})
        self.shares: Dict[RequirementOwner, List[str]] = {
            owner: list(codes) for owner, codes in (shares or {}).items()}

    def _key(self, code: str) -> str:
        """The same key for every equivalent of ``code``."""
        return min(self.catalog.equivalents(code)) if code in self.catalog else code

    def is_overlap(self, code: str, owner: RequirementOwner) -> bool:
        """
        Whether ``owner`` could count ``code`` only by sharing it with programs
        that already count it.
        """
        held = self.owners.get(self._key(code))
        return (bool(held) and owner not in held
                and all(rules.may_share(h.kind, owner.kind) for h in held))

    def can_claim(self, code: str, owner: RequirementOwner) -> bool:
        """Whether ``code`` may count toward a requirement of ``owner``."""
        if self._key(code) not in self.owners:
            return True
        if not self.is_overlap(code, owner):
            return False
        return rules.within_overlap_limit(owner.kind, self.shared(owner) + (code,), self.catalog,
                                          owner.max_major_overlap_courses)

    def claim(self, code: str, owner: RequirementOwner) -> None:
        """Count ``code`` toward ``owner`` (call ``can_claim`` first); repeating it is a no-op."""
        key = self._key(code)
        held = self.owners.setdefault(key, [])
        self.codes.setdefault(key, code)
        if owner in held:
            return
        if held:
            self.shares.setdefault(owner, []).append(code)
        held.append(owner)

    def courses_of(self, owner: RequirementOwner) -> List[str]:
        """Every course ``owner`` counts, in the order they were first claimed."""
        return [self.codes[key] for key, held in self.owners.items() if owner in held]

    def shared(self, owner: RequirementOwner) -> Tuple[str, ...]:
        """The courses ``owner`` counts that an earlier program counted first, in order."""
        return tuple(self.shares.get(owner, ()))

    def copy(self) -> 'ClaimLedger':
        return ClaimLedger(self.catalog, self.owners, self.shares, self.codes)
