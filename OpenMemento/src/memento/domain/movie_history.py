"""Bounded session history of movie plans, without media or analysis copies."""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from memento.domain.movie import MoviePlan


class MovieHistory:
    def __init__(self, limit: int = 50):
        if type(limit) is not int or limit < 1:
            raise ValueError("Die Historie muss mindestens eine Änderung behalten.")
        self.limit = limit
        self._plans: list[MoviePlan] = []
        self._position = -1

    @property
    def can_undo(self):
        return self._position > 0

    @property
    def can_redo(self):
        return self._position + 1 < len(self._plans)

    @property
    def current(self):
        return deepcopy(self._plans[self._position]) if self._plans else None

    def reset(self, plan: MoviePlan):
        plan.validate()
        self._plans = [deepcopy(plan)]
        self._position = 0

    def record(self, plan: MoviePlan):
        """Record only successfully saved changes; a no-op preserves redo."""
        plan.validate()
        if self._plans and plan == self._plans[self._position]:
            return
        del self._plans[self._position + 1:]
        self._plans.append(deepcopy(plan))
        self._plans = self._plans[-(self.limit + 1):]
        self._position = len(self._plans) - 1

    def restore(self, direction: int, save: Callable[[MoviePlan], None]) -> MoviePlan | None:
        """Save before moving the cursor so a disk failure cannot consume a step."""
        if direction not in (-1, 1):
            raise ValueError("Ungültige Richtung für die Filmhistorie.")
        if not (self.can_undo if direction == -1 else self.can_redo):
            return None
        position = self._position + direction
        plan = deepcopy(self._plans[position])
        save(plan)
        self._position = position
        return plan
