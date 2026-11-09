"""Global allocation optimiser: OR-Tools CP-SAT with a genuine lexicographic (multi-stage) objective.

WHY CP-SAT, NOT MIN-COST FLOW
  Min-cost max-flow can model "one team -> one mentor with a per-mentor cost", but this policy needs *non-linear,
  cross-mentor* objectives (worst overload, spread of relative utilisation, sums of squares). Those are not
  expressible as per-edge costs, so a flow model could only approximate them. CP-SAT states them exactly.

WHY LEXICOGRAPHIC STAGES, NOT ONE WEIGHTED SUM
  Strict priorities encoded as huge weights (1e9*a + 1e6*b + ...) risk integer overflow and silently let a lower
  priority win. Instead each stage optimises ONE objective, then the achieved value is added to the model as a hard
  constraint before the next stage runs. Earlier priorities can therefore never be traded away for later ones.

DECISION VARIABLES
  x[t,f] = 1  if team t is assigned to faculty f. Only *compatible* pairs get a variable (the caller has already applied
  every mandatory eligibility rule and the domain-compatibility rule), so an incompatible mentor can never be chosen.
  Capacity is NOT a hard constraint: overload is allowed but optimised (controlled overload).

STAGES (priority order, highest first)
   1 assigned      maximise number of teams given a compatible mentor
   2 worst_over    minimise the worst overload   max_f max(0, load_f - capacity_f)
   3 total_over    minimise total overload       sum_f max(0, load_f - capacity_f)
   4 tier_primary  maximise teams placed on a PRIMARY-domain mentor
   5 tier_additional maximise teams placed on an ADDITIONAL-domain mentor (=> related-only matches are minimised)
   6 exact_matches maximise the number of exactly matched project domains (multi-domain mentors preferred)
   7 related_matches maximise the number of related (parent/child) domain matches
   8 util_spread   minimise  max_f u_f - min_f u_f     where u_f = ceil(1000 * load_f / capacity_f)  (balance)
   9 util_peak     minimise  max_f u_f
  10 util_squares  minimise  sum_f u_f^2                 (convex fairness tie-break)
  11 preference    maximise the secondary preference score (expertise > supported, interests, department)
  12 tiebreak_fac  prefer lower faculty ids overall                 (deterministic tie-break)
  13 tiebreak_pair prefer a fixed (team rank x faculty rank) pairing (deterministic tie-break)
  load_f = existing workload that stays fixed + the teams assigned to f in this run.

TRADE-OFF (documented): domain-match quality (stages 4-7) outranks balancing of *within-capacity* utilisation
(stages 8-10), so a primary-domain mentor is not bypassed merely because another mentor is less busy. Overload is
different: it is minimised first (stages 2-3), so a mentor who would be pushed over capacity is bypassed in favour of a
less-ideal but compatible mentor whenever that avoids overload.

DETERMINISM: inputs are sorted, a fixed seed and a single worker are used, and the model is built in sorted order, so
unchanged inputs give identical output. (Only an expired time limit can change the result, and that is reported.)
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

SCALE = 1000          # utilisation is measured in 1/1000 of capacity so that it stays an integer


class SolverError(Exception):
    """The optimiser could not produce a usable result. ``code`` is one of: timeout, infeasible, failed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Edge:
    tier: int            # 1 primary, 2 additional, 3 related
    exact: int           # number of exactly matched domains
    related: int         # number of related (parent/child) matches
    pref: int            # secondary preference score * 100


@dataclass
class SolveResult:
    assignment: dict[int, int]                         # team_id -> faculty_id
    stages: list[dict] = field(default_factory=list)
    proved_optimal: bool = True
    seconds: float = 0.0


def _status_name(st) -> str:
    return {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible",
            cp_model.MODEL_INVALID: "invalid", cp_model.UNKNOWN: "unknown"}.get(st, str(st))


def solve(team_ids: list[int], base: dict[int, int], cap: dict[int, int], edges: dict[tuple[int, int], Edge],
          time_limit: float = 30.0, workers: int = 1) -> SolveResult:
    """Assign every team that has at least one edge. ``base``/``cap`` map faculty id -> fixed load / capacity."""
    t0 = time.monotonic()
    teams = sorted({t for t, _ in edges} & set(team_ids))
    if not teams:
        return SolveResult({}, [], True, 0.0)
    keys = sorted(edges)
    facs = sorted({f for _, f in keys})
    if any(cap[f] <= 0 for f in facs):
        raise SolverError("failed", "Internal error: a faculty member without capacity was offered to the optimiser.")
    f_rank = {f: i for i, f in enumerate(facs)}
    t_rank = {t: i for i, t in enumerate(teams)}
    
    m = cp_model.CpModel()
    x = {k: m.NewBoolVar(f"x_{k[0]}_{k[1]}") for k in keys}
    by_team: dict[int, list] = defaultdict(list)
    by_fac: dict[int, list] = defaultdict(list)
    for (t, f), v in x.items():
        by_team[t].append(v)
        by_fac[f].append(v)
    for t in teams:
        m.AddAtMostOne(by_team[t])

    load, over, util, util_ub = {}, {}, {}, {}
    for f in facs:
        ub = base[f] + len(by_fac[f])
        load[f] = base[f] + sum(by_fac[f])
        over[f] = m.NewIntVar(0, ub, f"over_{f}")
        m.Add(over[f] >= load[f] - cap[f])
        util_ub[f] = (SCALE * ub + cap[f] - 1) // cap[f]
        util[f] = m.NewIntVar(0, util_ub[f], f"util_{f}")
        # exact ceiling: util = ceil(SCALE * load / cap)  (both bounds, otherwise the solver could inflate util)
        m.Add(cap[f] * util[f] >= SCALE * load[f])
        m.Add(cap[f] * util[f] <= SCALE * load[f] + cap[f] - 1)
    worst = m.NewIntVar(0, max(base[f] + len(by_fac[f]) for f in facs), "worst_over")
    for f in facs:
        m.Add(worst >= over[f])
    u_max_ub = max(util_ub.values())
    u_max = m.NewIntVar(0, u_max_ub, "u_max")
    u_min = m.NewIntVar(0, u_max_ub, "u_min")
    for f in facs:
        m.Add(u_max >= util[f])
        m.Add(u_min <= util[f])
    squares = []
    for f in facs:
        sq = m.NewIntVar(0, util_ub[f] ** 2, f"sq_{f}")
        m.AddMultiplicationEquality(sq, [util[f], util[f]])
        squares.append(sq)
    if len(facs) == 1:                     # spread is meaningless with a single participant
        m.Add(u_max == u_min)

    def weighted(fn):
        return sum(fn(k) * x[k] for k in keys)

    def constant_per_team(fn) -> bool:
        """True when every team sees the same coefficient on all its edges (objective cannot vary)."""
        per = defaultdict(set)
        for (t, f) in keys:
            per[t].add(fn((t, f)))
        return all(len(s) == 1 for s in per.values())

    # (name, sense, expression, constant-check callable or None)
    stages = [
        ("assigned", "max", sum(x.values()), None),
        ("worst_overload", "min", worst, None),
        ("total_overload", "min", sum(over.values()), None),
        ("primary_matches", "max", weighted(lambda k: 1 if edges[k].tier == 1 else 0), lambda k: 1 if edges[k].tier == 1 else 0),
        ("additional_matches", "max", weighted(lambda k: 1 if edges[k].tier == 2 else 0), lambda k: 1 if edges[k].tier == 2 else 0),
        ("exact_domain_matches", "max", weighted(lambda k: edges[k].exact), lambda k: edges[k].exact),
        ("related_domain_matches", "max", weighted(lambda k: edges[k].related), lambda k: edges[k].related),
        ("utilisation_spread", "min", u_max - u_min, None),
        ("utilisation_peak", "min", u_max, None),
        ("utilisation_squares", "min", sum(squares), None),
        ("preference_score", "max", weighted(lambda k: edges[k].pref), lambda k: edges[k].pref),
        ("tiebreak_faculty", "min", weighted(lambda k: f_rank[k[1]]), lambda k: f_rank[k[1]]),
        ("tiebreak_pairing", "min", weighted(lambda k: (f_rank[k[1]] + 1) * (t_rank[k[0]] + 1)),
         lambda k: (f_rank[k[1]] + 1) * (t_rank[k[0]] + 1)),
    ]

    solution: dict[tuple[int, int], int] | None = None
    report, proved = [], True
    for name, sense, expr, const_fn in stages:
        left = time_limit - (time.monotonic() - t0)
        if solution is not None and const_fn is not None and constant_per_team(const_fn):
            report.append({"stage": name, "status": "skipped", "reason": "objective is constant for these inputs"})
            continue
        if solution is not None and left <= 0.05:
            report.append({"stage": name, "status": "skipped", "reason": "time limit reached"})
            proved = False
            continue
        if sense == "max":
            m.Maximize(expr)
        else:
            m.Minimize(expr)
        if solution is not None:
            m.ClearHints()
            for k, v in solution.items():
                m.AddHint(x[k], v)
        solver = cp_model.CpSolver()
        # fair share of the remaining budget for this and all later non-trivial stages
        share = max(0.2, left / max(1, len(stages) - len(report)))
        solver.parameters.max_time_in_seconds = max(0.2, min(left, share * 2 if name == "assigned" else share))
        solver.parameters.num_workers = max(1, workers)
        solver.parameters.random_seed = 20260101
        solver.parameters.log_search_progress = False
        ts = time.monotonic()
        try:
            st = solver.Solve(m)
        except Exception as exc:                                    # pragma: no cover - defensive
            raise SolverError("failed", "The optimiser failed unexpectedly.") from exc
        secs = round(time.monotonic() - ts, 3)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if solution is None:
                if st == cp_model.INFEASIBLE:
                    raise SolverError("infeasible", "No allocation satisfies the mandatory rules.")
                if st == cp_model.UNKNOWN:
                    raise SolverError("timeout", f"The optimiser found no solution within {time_limit:g} s.")
                raise SolverError("failed", "The optimiser failed unexpectedly.")
            report.append({"stage": name, "status": _status_name(st), "seconds": secs,
                           "reason": "no improvement within the time limit; previous result kept"})
            proved = False
            continue
        value = round(solver.ObjectiveValue())
        solution = {k: solver.Value(v) for k, v in x.items()}
        optimal = st == cp_model.OPTIMAL
        if not optimal:
            proved = False
        report.append({"stage": name, "status": _status_name(st), "value": value, "seconds": secs,
                       "proved_optimal": optimal})
        # lock this priority level before the next one runs
        if sense == "max":
            m.Add(expr >= value)
        else:
            m.Add(expr <= value)

    assert solution is not None
    assignment = {t: f for (t, f), v in solution.items() if v}
    return SolveResult(assignment, report, proved, round(time.monotonic() - t0, 3))
