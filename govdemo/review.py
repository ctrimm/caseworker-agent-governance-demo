"""Red herring test: seed the review queue with known-wrong items and measure the catch rate.

Everything here is a SIMULATION. The reviewer models are assumptions, not data about
real people. What is real is the method: you can only tell oversight from a green
button by measuring what reviewers do with items you know are wrong.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .tools import threshold_for


@dataclass
class QueueItem:
    case_id: str
    income: float
    household: int
    claimed_eligible: bool
    is_red_herring: bool

    @property
    def correct_eligible(self) -> bool:
        return self.income <= threshold_for(self.household)


def build_queue(n=200, red_herring_rate=0.05, seed=7) -> list[QueueItem]:
    """Each item is a drafted determination. Red herrings claim the opposite of what
    the item's own numbers say, which a reviewer can catch by reading the numbers."""
    rng = random.Random(seed)
    herrings = set(rng.sample(range(n), max(1, round(n * red_herring_rate))))
    items = []
    for i in range(n):
        household = rng.randint(1, 6)
        limit = threshold_for(household)
        income = round(rng.uniform(0.6, 1.4) * limit, -2)
        correct = income <= limit
        items.append(QueueItem(f"Q-{i:04d}", income, household,
                               (not correct) if i in herrings else correct, i in herrings))
    return items


class RubberStamp:
    """Approves nearly everything without looking. Approve is one click."""
    name = "rubber stamp"

    def __init__(self, seed=1, p_approve=0.97):
        self.rng, self.p = random.Random(seed), p_approve

    def approves(self, item: QueueItem) -> bool:
        return self.rng.random() < self.p


class Attentive:
    """Reads the numbers. Catches most wrong items and rarely rejects good ones."""
    name = "attentive"

    def __init__(self, seed=2, p_catch=0.9, p_false_reject=0.02):
        self.rng, self.p_catch, self.p_fr = random.Random(seed), p_catch, p_false_reject

    def approves(self, item: QueueItem) -> bool:
        if item.is_red_herring:
            return self.rng.random() >= self.p_catch
        return self.rng.random() >= self.p_fr


def measure(queue, reviewer) -> dict:
    herrings = [i for i in queue if i.is_red_herring]
    caught = sum(1 for i in herrings if not reviewer.approves(i))
    normal = [i for i in queue if not i.is_red_herring]
    false_rejects = sum(1 for i in normal if not reviewer.approves(i))
    return {
        "reviewer": reviewer.name, "items": len(queue), "red_herrings": len(herrings),
        "caught": caught, "catch_rate": caught / len(herrings),
        "approval_rate": 1 - (caught + false_rejects) / len(queue),
    }
