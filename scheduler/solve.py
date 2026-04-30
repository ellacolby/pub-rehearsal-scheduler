from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .model import Avail, Dance, Dancer, Slot
from .parse import dancer_availability_at


@dataclass
class MissReport:
    """One dancer who would miss (or be inconvenienced by) a particular rehearsal."""
    dancer_display: str
    casting_name: str
    avail: Avail   # ORANGE or RED


@dataclass
class ScheduleEntry:
    dance: Dance
    slot: Slot
    misses: list[MissReport]
    movable: list[MissReport]
    unknown_dancers: list[str]


@dataclass
class Schedule:
    entries: list[ScheduleEntry]
    unscheduled: list[Dance] = field(default_factory=list)
    total_penalty: int = 0
    total_red: int = 0
    total_orange: int = 0


def solve(
    dances: list[Dance],
    dancers: list[Dancer],
    candidate_slots: list[Slot],
    dancer_lookup: dict[str, Dancer],
    *,
    orange_penalty: int = 1,
    red_penalty: int = 100,
    num_options: int = 5,
    time_limit_seconds: int = 30,
) -> list[Schedule]:
    """Find up to `num_options` distinct schedules ranked by total penalty.

    A dance may be left unscheduled if there aren't enough non-overlapping rooms;
    the unscheduled penalty is much larger than red/orange so the solver prefers
    a slot with conflicts over leaving the dance off the schedule entirely."""

    # Map each dance to the dancers (by index) it includes
    dancer_idx_by_full = {d.full_name: i for i, d in enumerate(dancers)}
    dance_dancer_idx: list[set[int]] = []
    for dance in dances:
        idxs: set[int] = set()
        for casting_name in dance.dancers:
            d = dancer_lookup.get(casting_name)
            if d is not None and d.full_name in dancer_idx_by_full:
                idxs.add(dancer_idx_by_full[d.full_name])
        dance_dancer_idx.append(idxs)

    # Internally scale penalties so the duration tiebreaker (1 unit per extra 30 min)
    # ranks below dancer-conflict penalties but above ties.
    SCALE = 100
    o_int = orange_penalty * SCALE
    r_int = red_penalty * SCALE

    # Pre-compute per-(dance, slot) penalty (in scaled internal units)
    penalties: list[list[int]] = []
    for dance in dances:
        row: list[int] = []
        for slot in candidate_slots:
            row.append(_dance_slot_penalty(dance, slot, dancer_lookup, o_int, r_int))
        penalties.append(row)

    # Identify overlapping slot pairs (same day + overlapping times)
    same_room_overlap: list[tuple[int, int]] = []
    diff_room_overlap: list[tuple[int, int]] = []
    n_slots = len(candidate_slots)
    for i in range(n_slots):
        si = candidate_slots[i]
        for j in range(i + 1, n_slots):
            sj = candidate_slots[j]
            if si.day_of_week != sj.day_of_week:
                continue
            if not (si.start < sj.end and sj.start < si.end):
                continue
            if si.room == sj.room:
                same_room_overlap.append((i, j))
            else:
                diff_room_overlap.append((i, j))

    # Penalty for leaving a dance unscheduled — dwarfs any conflict penalty
    unscheduled_penalty = max(r_int, o_int, 1) * 1000
    # Tiebreaker: small bonus per extra 30-min cell beyond a 1-hour slot
    duration_bonus_per_extra_cell = 1

    excluded_assignments: list[frozenset[tuple[int, int]]] = []
    schedules: list[Schedule] = []
    for _ in range(num_options):
        result = _solve_one(
            dances, dancers, candidate_slots, dance_dancer_idx,
            same_room_overlap, diff_room_overlap,
            penalties, unscheduled_penalty, duration_bonus_per_extra_cell,
            excluded_assignments, time_limit_seconds,
        )
        if result is None:
            break
        assignment = result
        excluded_assignments.append(frozenset(assignment.items()))
        schedules.append(_build_schedule(
            dances, candidate_slots, dancer_lookup,
            assignment, orange_penalty, red_penalty,
        ))
    return schedules


def _solve_one(
    dances, dancers, candidate_slots, dance_dancer_idx,
    same_room_overlap, diff_room_overlap,
    penalties, unscheduled_penalty, duration_bonus_per_extra_cell,
    excluded, time_limit_seconds,
):
    n_dances = len(dances)
    n_slots = len(candidate_slots)
    if n_dances == 0:
        return None

    model = cp_model.CpModel()
    assign = {}
    for d_idx in range(n_dances):
        for s_idx in range(n_slots):
            assign[(d_idx, s_idx)] = model.NewBoolVar(f"x_{d_idx}_{s_idx}")

    # Each dance gets at most one slot (allowed to be unscheduled, with high penalty)
    for d_idx in range(n_dances):
        model.Add(sum(assign[(d_idx, s_idx)] for s_idx in range(n_slots)) <= 1)

    # Each (room, day, time) cell holds at most one dance
    for s_idx in range(n_slots):
        model.Add(sum(assign[(d_idx, s_idx)] for d_idx in range(n_dances)) <= 1)

    # No two dances share an overlapping slot in the same room
    for i, j in same_room_overlap:
        terms = [assign[(d, i)] for d in range(n_dances)] + [assign[(d, j)] for d in range(n_dances)]
        model.Add(sum(terms) <= 1)

    # No dancer in two dances at overlapping times (any rooms)
    overlap_pairs = same_room_overlap + diff_room_overlap
    n_dancers = len(dancers)
    for dancer_idx in range(n_dancers):
        dance_indices = [d for d, dset in enumerate(dance_dancer_idx) if dancer_idx in dset]
        if len(dance_indices) < 2:
            continue
        for i, j in overlap_pairs:
            terms = []
            for d in dance_indices:
                terms.append(assign[(d, i)])
                terms.append(assign[(d, j)])
            model.Add(sum(terms) <= 1)

    # No-good cuts to enumerate distinct top-N solutions
    for excl in excluded:
        if excl:
            model.Add(sum(assign[k] for k in excl) <= len(excl) - 1)

    # Objective: priority-weighted (conflict penalties − unscheduled cost − duration bonus).
    # Higher priority dances pay more if unscheduled, gain more from longer slots, and are
    # more strongly nudged toward conflict-free slots.
    obj_terms = []
    for d_idx in range(n_dances):
        priority = max(1, getattr(dances[d_idx], "priority", 1))
        for s_idx in range(n_slots):
            slot = candidate_slots[s_idx]
            extra_cells = max(0, _slot_minutes(slot) - 60) // 30
            coef = priority * (
                penalties[d_idx][s_idx]
                - unscheduled_penalty
                - duration_bonus_per_extra_cell * extra_cells
            )
            obj_terms.append(coef * assign[(d_idx, s_idx)])
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignment: dict[int, int] = {}
    for d_idx in range(n_dances):
        for s_idx in range(n_slots):
            if solver.Value(assign[(d_idx, s_idx)]) == 1:
                assignment[d_idx] = s_idx
                break
    return assignment


def _slot_minutes(slot: Slot) -> int:
    sh, sm = map(int, slot.start.split(":"))
    eh, em = map(int, slot.end.split(":"))
    return (eh * 60 + em) - (sh * 60 + sm)


def _dance_slot_penalty(
    dance: Dance, slot: Slot,
    dancer_lookup: dict[str, Dancer],
    orange_penalty: int, red_penalty: int,
) -> int:
    total = 0
    for casting_name in dance.dancers:
        dancer = dancer_lookup.get(casting_name)
        if dancer is None:
            continue
        avail = dancer_availability_at(dancer, slot)
        if avail == Avail.ORANGE:
            total += orange_penalty
        elif avail == Avail.RED:
            total += red_penalty
    return total


def _build_schedule(
    dances, candidate_slots, dancer_lookup,
    assignment, orange_penalty, red_penalty,
) -> Schedule:
    entries: list[ScheduleEntry] = []
    unscheduled: list[Dance] = []
    total_red = 0
    total_orange = 0
    for d_idx, dance in enumerate(dances):
        if d_idx not in assignment:
            unscheduled.append(dance)
            continue
        slot = candidate_slots[assignment[d_idx]]
        misses: list[MissReport] = []
        movable: list[MissReport] = []
        unknown: list[str] = []
        for casting_name in dance.dancers:
            dancer = dancer_lookup.get(casting_name)
            if dancer is None:
                unknown.append(casting_name)
                continue
            avail = dancer_availability_at(dancer, slot)
            report = MissReport(
                dancer_display=dancer.display_name,
                casting_name=casting_name,
                avail=avail,
            )
            if avail == Avail.RED:
                misses.append(report)
                total_red += 1
            elif avail == Avail.ORANGE:
                movable.append(report)
                total_orange += 1
        entries.append(ScheduleEntry(
            dance=dance, slot=slot,
            misses=misses, movable=movable, unknown_dancers=unknown,
        ))
    total_penalty = total_red * red_penalty + total_orange * orange_penalty
    return Schedule(
        entries=entries,
        unscheduled=unscheduled,
        total_penalty=total_penalty,
        total_red=total_red,
        total_orange=total_orange,
    )
