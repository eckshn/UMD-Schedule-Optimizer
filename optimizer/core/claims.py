"""Which degree program counts each course, shared by course selection and the degree audit."""

from typing import Dict, List, Mapping, Optional, Tuple

from ..models.catalog import Catalog
from ..models.student import RequirementOwner
from . import rules


class ClaimLedger:
    """
    The program (major or minor) each course counts toward.

    A course counts toward one program only, except where ``rules.may_share``
    allows it (a minor may count courses a major claimed), as long as every
    course a program shares that way stays within
    ``rules.within_major_minor_overlap``. A course is shared at most once, so
    it can't count toward a second minor. Works for any number of majors and
    minors. Courses that only "degree" requirements use (gen-eds, credit
    minimums) are never claimed.
    """

    def __init__(self, catalog: Catalog,
                 owners: Optional[Mapping[str, RequirementOwner]] = None,
                 shares: Optional[Mapping[RequirementOwner, List[str]]] = None):
        self.catalog = catalog
        self.owners: Dict[str, RequirementOwner] = dict(owners or {})
        self.shares: Dict[RequirementOwner, List[str]] = {
            minor: list(codes) for minor, codes in (shares or {}).items()}

    def is_overlap(self, code: str, owner: RequirementOwner) -> bool:
        """Whether ``owner`` could count ``code`` only by sharing it with the program that claimed it."""
        claimer = self.owners.get(code)
        return (claimer is not None and claimer != owner
                and rules.may_share(claimer.kind, owner.kind))

    def can_claim(self, code: str, owner: RequirementOwner) -> bool:
        """Whether ``code`` may count toward a requirement of ``owner``."""
        if code not in self.owners:
            return True
        if not self.is_overlap(code, owner):
            return False
        if any(code in codes for codes in self.shares.values()):
            return False
        return rules.within_major_minor_overlap(self.shared(owner) + (code,), self.catalog,
                                                owner.max_major_overlap_courses)

    def claim(self, code: str, owner: RequirementOwner) -> None:
        """Count ``code`` toward ``owner`` (call ``can_claim`` first); repeating it is a no-op."""
        claimer = self.owners.setdefault(code, owner)
        if claimer != owner:
            codes = self.shares.setdefault(owner, [])
            if code not in codes:
                codes.append(code)

    def shared(self, owner: RequirementOwner) -> Tuple[str, ...]:
        """The courses ``owner`` shares with other programs, in the order it took them."""
        return tuple(self.shares.get(owner, ()))

    def copy(self) -> 'ClaimLedger':
        return ClaimLedger(self.catalog, self.owners, self.shares)
