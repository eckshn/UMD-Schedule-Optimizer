"""Gen-ed option bookkeeping shared by course selection and the degree audit."""

from typing import Dict, Optional, Tuple

from ..models.catalog import Catalog
from . import rules


class GenEdLedger:
    """
    The gen-ed option each course is counted under.

    ``Course.gen_ed_options`` are alternatives: the first time a course counts
    toward a category it is locked to the option holding that category, and it
    can then count toward that option's other categories only.
    """

    def __init__(self, catalog: Catalog, locked: Optional[Dict[str, Tuple[str, ...]]] = None):
        self.catalog = catalog
        self.locked: Dict[str, Tuple[str, ...]] = dict(locked or {})

    def option_for(self, code: str, category: str) -> Optional[Tuple[str, ...]]:
        """The option ``code`` would count under toward ``category``, or None if it can't."""
        satisfying = rules.gen_ed_categories_satisfying(category)
        if code in self.locked:
            option = self.locked[code]
            return option if any(c in option for c in satisfying) else None
        course = self.catalog.get(code)
        for c in satisfying if course else ():
            option = course.get_gen_ed_option_for_category(c)
            if option is not None:
                return tuple(option)
        return None

    def count(self, code: str, category: str) -> bool:
        """Count ``code`` toward ``category``, locking its option; False if it can't count."""
        option = self.option_for(code, category)
        if option is not None:
            self.locked[code] = option
        return option is not None

    def copy(self) -> 'GenEdLedger':
        return GenEdLedger(self.catalog, self.locked)
