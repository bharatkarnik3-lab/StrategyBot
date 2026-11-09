"""Paired, reproducible comparisons with a previous single-file bot.

Example: python tools/compare.py --reference /tmp/previous.py --maps 16 --seed 200
Use --head-to-head to play the candidate against three copies of the reference.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.simulate import Baseline, load_bot, play


def benchmark(path, reference, maps, seed_start, kinds, head_to_head):
    records, durations = [], []
    for seed in range(seed_start, seed_start + maps):
        for seat in range(4):
            if head_to_head:
                controllers = [load_bot(reference, f"opponent_{j}") for j in range(4)]
            else:
                controllers = [Baseline(kinds[(j-seat-1) % 4 % 3], seed*31+j) for j in range(4)]
            controllers[seat] = load_bot(path, "comparison_candidate")
            game, times = play(controllers, seed, check_inputs=True)
            own = game.scores[seat+1]
            others = [score for j, score in enumerate(game.scores[1:]) if j != seat]
            records.append({"seed": seed, "seat": seat+1, "scores": game.scores[1:],
                            "rank": 1 + sum(score > own for score in others),
                            "pairwise_points": sum(1 if own > score else 0.5 if own == score else 0
                                                   for score in others)})
            durations.extend(times[seat])
    durations.sort()
    return {"games": len(records),
            "first_places_including_ties": sum(r["rank"] == 1 for r in records),
            "pairwise_win_rate": round(sum(r["pairwise_points"] for r in records)/(3*len(records)), 4),
            "mean_score": round(sum(r["scores"][r["seat"]-1] for r in records)/len(records), 2),
            "mean_rank": round(sum(r["rank"] for r in records)/len(records), 3),
            "decision_ms_p95": round(1000*durations[int(0.95*(len(durations)-1))], 3),
            "decision_ms_max": round(1000*max(durations), 3), "results": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot", type=Path, default=Path(__file__).resolve().parents[1]/"bot.py")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--maps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=200)
    parser.add_argument("--opponents", default="greedy,upgrade,raider")
    parser.add_argument("--head-to-head", action="store_true")
    args = parser.parse_args()
    kinds = args.opponents.split(",")
    if args.maps < 1:
        parser.error("--maps must be positive")
    if len(kinds) != 3 or any(k not in {"greedy", "upgrade", "raider", "fortress", "random", "stay"} for k in kinds):
        parser.error("--opponents must contain three known baseline names")
    if not args.bot.is_file() or not args.reference.is_file():
        parser.error("Both bot files must exist")
    results = {"seed_start": args.seed, "maps": args.maps,
               "lineup": "three reference bots" if args.head_to_head else kinds}
    for name, path in (("reference", args.reference), ("candidate", args.bot)):
        results[name] = benchmark(path, args.reference, args.maps, args.seed, kinds, args.head_to_head)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
