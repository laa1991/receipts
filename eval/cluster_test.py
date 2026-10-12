"""The right test for this design: a cluster bootstrap over tasks.

Samples within a task are not independent (same question, same seeder facts), so treating
each answer as an independent observation overstates the evidence — that is what the
non-overlapping Wilson intervals do. And the sign test throws away magnitude, which is what
makes it look weaker than it is.

The paired, cluster-aware answer: resample *tasks* with replacement, aggregate the answers
inside each resampled task, and look at the distribution of the difference. It keeps the
pairing and respects the clustering.

    python eval/cluster_test.py eval/overclaim-run5.json [--iters 4000]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(path: str) -> dict[str, dict[str, list[tuple[int, int]]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    by_task: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    for r in data["rows"]:
        by_task[r["question"]][r["arm"]].append((r["unbacked"], r["claims"]))
    return {q: dict(arms) for q, arms in by_task.items() if len(arms) == 2}


def rate(pairs: list[tuple[int, int]]) -> tuple[int, int]:
    return sum(u for u, _ in pairs), sum(c for _, c in pairs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    tasks = load(args.path)
    names = sorted(tasks)
    print(f"{len(names)} paired tasks, {args.iters} bootstrap resamples")

    pu, pc = 0, 0
    ru, rc = 0, 0
    for q in names:
        u, c = rate(tasks[q]["plain"])
        pu, pc = pu + u, pc + c
        u, c = rate(tasks[q]["receipts"])
        ru, rc = ru + u, rc + c
    point = (pu / pc) - (ru / rc)
    print(f"observed: plain {pu}/{pc} = {pu/pc:.0%} · receipts {ru}/{rc} = {ru/rc:.0%} "
          f"· difference {point:+.1%}")

    rng = random.Random(args.seed)
    deltas = []
    for _ in range(args.iters):
        pick = [rng.choice(names) for _ in names]
        au = ac = bu = bc = 0
        for q in pick:
            u, c = rate(tasks[q]["plain"])
            au, ac = au + u, ac + c
            u, c = rate(tasks[q]["receipts"])
            bu, bc = bu + u, bc + c
        if ac and bc:
            deltas.append((au / ac) - (bu / bc))
    deltas.sort()
    lo = deltas[int(0.025 * len(deltas))]
    hi = deltas[int(0.975 * len(deltas))]
    share_le_zero = sum(1 for d in deltas if d <= 0) / len(deltas)
    print(f"cluster bootstrap 95% CI of the difference: [{lo:+.1%}, {hi:+.1%}]")
    print(f"resamples where receipts is NOT better: {share_le_zero:.1%}")

    # per-kind clusters, same procedure
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    kinds = sorted({r["kind"] for r in data["rows"]})
    print("\nby task kind (cluster bootstrap over tasks of that kind):")
    for kind in kinds:
        sub = {q: a for q, a in tasks.items()
               if any(r["kind"] == kind and r["question"] == q for r in data["rows"])}
        if not sub:
            continue
        names_k = sorted(sub)
        deltas_k = []
        for _ in range(min(args.iters, 2000)):
            pick = [rng.choice(names_k) for _ in names_k]
            au = ac = bu = bc = 0
            for q in pick:
                u, c = rate(sub[q]["plain"])
                au, ac = au + u, ac + c
                u, c = rate(sub[q]["receipts"])
                bu, bc = bu + u, bc + c
            if ac and bc:
                deltas_k.append((au / ac) - (bu / bc))
        if not deltas_k:
            continue
        deltas_k.sort()
        lo_k = deltas_k[int(0.025 * len(deltas_k))]
        hi_k = deltas_k[int(0.975 * len(deltas_k))]
        print(f"  {kind:14s} n={len(names_k):2d} tasks · difference "
              f"[{lo_k:+.1%}, {hi_k:+.1%}] · P(not better)="
              f"{sum(1 for d in deltas_k if d <= 0)/len(deltas_k):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
