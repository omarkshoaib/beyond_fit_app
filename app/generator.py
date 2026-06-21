import logging
from typing import List, Dict, Any, Optional
from .models import Exercise, ClientProfile, WorkoutSlot, WorkoutDay, WorkoutWeek
from .exercise_db import get_exercise_db
from .domain.workout.constants import (
    VOLUME_LANDMARKS,
    REST_BY_FATIGUE,
    TEMPO_BY_PATTERN,
    CUES_BY_PATTERN,
    HARD_REFUSE_CONDITIONS,
    SUBSTITUTION_MAP,
    INJURY_CAVEATS,
)
from .domain.workout.warmup import build_warmup
from .models import WarmupSet

logger = logging.getLogger(__name__)


class SafetyRefusalError(Exception):
    """Raised when a client's health profile triggers a hard-refuse gate.

    The ``reason`` attribute contains the human-readable message for the coach.
    """
    def __init__(self, condition_key: str, reason: str) -> None:
        self.condition_key = condition_key
        self.reason = reason
        super().__init__(reason)

class AutoRegulator:
    @staticmethod
    def calculate_next_load(last_weight: float, last_target_rpe: float, last_actual_rpe: float, next_target_rpe: float) -> float:
        """
        Determines the target weight heuristically based on performance telemetry.
        """
        rpe_error = last_actual_rpe - last_target_rpe
        
        # Base weight correction logic
        if rpe_error > 0:
            corrected_baseline = last_weight - (rpe_error * 0.04 * last_weight)
        else:
            corrected_baseline = last_weight + (abs(rpe_error) * 0.04 * last_weight)
            
        # Add next week stimulus
        target_jump = next_target_rpe - last_target_rpe
        next_target = corrected_baseline + (target_jump * 0.025 * corrected_baseline)

        # Cap the weekly change to ±10% to match the check-in (derive_plan_delta)
        # path — an uncapped RPE-error correction could jump ~+20% in one week.
        next_target = max(last_weight * 0.90, min(last_weight * 1.10, next_target))

        return round(next_target / 2.5) * 2.5

# Mapping from primary_muscle tags in the DB to canonical budget keys
MUSCLE_TO_BUDGET_KEY: Dict[str, str] = {
    "quadriceps": "quadriceps",
    "hamstrings": "hamstrings",
    "glutes": "glutes",
    "calves": "calves",
    "chest": "chest",
    "upper_chest": "chest",
    "lats": "back",
    "mid_back": "back",
    "front_delts": "shoulders",
    "side_delts": "shoulders",
    "rear_delts": "shoulders",
    "biceps": "arms",
    "triceps": "arms",
}

class WorkoutGenerator:
    def __init__(self, config: Optional[Dict] = None):
        raw_db = get_exercise_db()
        self.exercise_db: List[Exercise] = [Exercise(**ex) for ex in raw_db]
        if config is None:
            from app.settings import get_settings
            config = get_settings().workout_constants
        self._cfg = config
        self.last_generation_notes: List[str] = []

    # ── Split Routing ──────────────────────────────────────────────
    def _resolve_split(self, avatar: str, days: int) -> List[str]:
        if days == 2:
            return ["Full Body A", "Full Body B"]
        elif days == 3:
            if avatar == "powerlifter":
                return ["Squat Day", "Bench Day", "Deadlift Day"]
            elif avatar == "powerbuilder":
                return ["Upper", "Lower", "Full Body A"]
            else:
                return ["Full Body A", "Full Body B", "Full Body A"]
        elif days == 4:
            if avatar == "powerlifter":
                return ["Squat Day", "Bench Day", "Deadlift Day", "Accessory/GPP Day"]
            elif avatar == "powerbuilder":
                return ["Upper Power", "Lower Power", "Upper Hypertrophy", "Lower Hypertrophy"]
            else:
                return ["Upper", "Lower", "Upper", "Lower"]
        elif days == 5:
            return ["Upper", "Lower", "Push", "Pull", "Legs"]
        elif days == 6:
            return ["Push", "Pull", "Legs", "Push", "Pull", "Legs"]
        else:
            return [f"Training Day {i+1}" for i in range(days)]

    # ── Volume Budget ──────────────────────────────────────────────
    def _budget_volume(self, experience_level: str) -> Dict[str, int]:
        vb = self._cfg["volume_budget"]
        if experience_level == "beginner":
            base_sets = vb["beginner_base_sets"]
        elif experience_level == "intermediate":
            base_sets = vb["intermediate_base_sets"]
        else:
            base_sets = vb["advanced_base_sets"]

        return {
            "quadriceps": base_sets,
            "hamstrings": base_sets,
            "glutes": base_sets,
            "calves": base_sets,
            "chest": base_sets,
            "back": base_sets,
            "shoulders": base_sets,
            "arms": base_sets,
        }

    # ── Periodization ──────────────────────────────────────────────
    def _calculate_rpe(self, week_number: int) -> float:
        rpe_list: List[float] = self._cfg["periodization"]["rpe_map"]
        block_length: int = self._cfg["periodization"]["block_length"]
        default_rpe: float = self._cfg["periodization"]["default_rpe"]
        week_in_block = ((week_number - 1) % block_length) + 1
        idx = week_in_block - 1
        return rpe_list[idx] if idx < len(rpe_list) else default_rpe

    def _is_deload(self, week_number: int) -> bool:
        block_length: int = self._cfg["periodization"]["block_length"]
        deload_week: int = self._cfg["periodization"]["deload_week"]
        return ((week_number - 1) % block_length) + 1 == deload_week

    # ── Exercise Filtering ─────────────────────────────────────────
    def _filter_exercises(self, client: ClientProfile, **kwargs) -> List[Exercise]:
        # `avatars`: the set of avatar tags acceptable for THIS slot. Defaults to the
        # client's own avatar; callers widen it (e.g. a powerlifter's accessory slots
        # also accept powerbuilder exercises) so the narrow powerlifter pool does not
        # collapse a day to 2 thin slots. Competition main lifts stay powerlifter-only.
        avatars = kwargs.pop("avatars", None) or {client.avatar}
        valid_exercises = []
        banned_patterns = self._banned_patterns(client)
        for ex in self.exercise_db:
            if not (set(ex.avatar_tags) & avatars):
                continue

            avail = client.available_equipment or ["full_gym"]   # empty -> wildcard (legacy-safe)
            has_equipment = True
            for eq in ex.equipment_required:
                if eq not in avail and "full_gym" not in avail:
                    has_equipment = False
                    break
            if not has_equipment:
                continue

            if ex.movement_pattern in banned_patterns:
                continue
            # lower_back_pain bans both hinge AND squat (per SUBSTITUTION_MAP), substituting
            # to lunge/horizontal_pull/horizontal_push; also strips lower_back secondary muscles.
            # Extra lower_back_pain guard: also strip movements loading lower_back
            # as a secondary muscle (e.g. barbell rows), regardless of pattern.
            if "lower_back_pain" in client.limitations and "lower_back" in ex.secondary_muscles:
                continue

            if "pattern" in kwargs and ex.movement_pattern != kwargs["pattern"]:
                continue
            if "primary_muscle" in kwargs and ex.primary_muscle != kwargs["primary_muscle"]:
                continue
            if "muscle_group" in kwargs:
                mg = kwargs["muscle_group"]
                upper_muscles = ["chest", "back", "shoulders", "arms", "front_delts", "side_delts", "rear_delts", "biceps", "triceps", "lats", "mid_back", "upper_chest"]
                lower_muscles = ["quadriceps", "hamstrings", "glutes", "calves"]
                if mg == "upper" and ex.primary_muscle not in upper_muscles:
                    continue
                if mg == "lower" and ex.primary_muscle not in lower_muscles:
                    continue
            if "bio_focus" in kwargs and ex.biomechanical_focus != kwargs["bio_focus"]:
                continue
            if "min_fatigue" in kwargs and ex.fatigue_cost < kwargs["min_fatigue"]:
                continue
            if "max_fatigue" in kwargs and ex.fatigue_cost > kwargs["max_fatigue"]:
                continue
            if "exact_fatigue" in kwargs and ex.fatigue_cost != kwargs["exact_fatigue"]:
                continue
            if "max_difficulty" in kwargs and ex.difficulty_tier > kwargs["max_difficulty"]:
                continue

            valid_exercises.append(ex)

        return valid_exercises

    def _banned_patterns(self, client: ClientProfile) -> set:
        """Movement patterns the client's limitations forbid (from SUBSTITUTION_MAP)."""
        banned: set = set()
        for lim in client.limitations:
            sub = SUBSTITUTION_MAP.get(lim)
            if sub:
                banned.update(sub.keys())
        return banned

    def _substitute_patterns(self, client: ClientProfile, pattern: str) -> list:
        """Safe replacement patterns for a banned pattern, across ALL limitations,
        excluding any replacement that is itself banned by another limitation.

        Returns [] when no safe replacement exists (all substitutes are themselves
        banned by a different limitation). Callers should treat an empty return as
        'no substitute available' — do NOT fall back to the original banned pattern."""
        banned = self._banned_patterns(client)
        candidates: list[str] = []
        for lim in client.limitations:
            for sub_pat in SUBSTITUTION_MAP.get(lim, {}).get(pattern, []):
                if sub_pat not in banned and sub_pat not in candidates:
                    candidates.append(sub_pat)
        # No safe substitute exists (all replacements are themselves banned) -> empty,
        # so Tier 5 fills nothing for this slot rather than retrying a banned pattern.
        return candidates

    # ── Budget helpers ─────────────────────────────────────────────
    def _budget_key(self, muscle: str) -> Optional[str]:
        return MUSCLE_TO_BUDGET_KEY.get(muscle)

    def _remaining_budget(self, budget: Dict[str, int], muscle: str) -> int:
        key = self._budget_key(muscle)
        if key is None:
            return 99  # unknown muscles are uncapped
        return budget.get(key, 0)

    def _spend_budget(self, budget: Dict[str, int], muscle: str, sets: int) -> int:
        key = self._budget_key(muscle)
        if key is None:
            return sets
        remaining = budget.get(key, 0)
        actual = min(sets, max(remaining, 0))
        budget[key] = remaining - actual
        return actual

    # ── Exercise Rotation ──────────────────────────────────────────
    def _rotation_idx(self, week_number: int, slot_type: str, pool_size: int) -> int:
        """
        Return the pool index to use for a given week and slot type.

        - main_lift:         stable for the full 5-week block
        - primary_accessory: rotates every 2 weeks within the block
        - isolation:         rotates every week
        """
        if pool_size <= 1:
            return 0
        block_length: int = self._cfg["periodization"]["block_length"]
        if slot_type in ("main_lift", "main_compound"):
            period = block_length           # same lift for the whole block
        elif slot_type in ("primary_accessory", "secondary_compound", "accessory"):
            period = 2                      # swap every 2 weeks
        else:
            period = 1                      # isolations rotate weekly
        # (week_number - 1) ensures week 1 starts at period 0
        return ((week_number - 1) // period) % pool_size

    # ── Template key mapping ───────────────────────────────────────
    _DAY_NAME_TO_TEMPLATE: Dict[str, str] = {
        "Full Body A":       "Full_Body_A",
        "Full Body B":       "Full_Body_B",
        "Squat Day":         "Squat_Day",
        "Bench Day":         "Bench_Day",
        "Deadlift Day":      "Deadlift_Day",
        "Accessory/GPP Day": "Accessory_GPP",
        "Upper Power":       "Upper_Power",
        "Lower Power":       "Lower_Power",
        "Upper Hypertrophy": "Upper_Hypertrophy",
        "Lower Hypertrophy": "Lower_Hypertrophy",
    }

    def _template_key(self, day_name: str) -> str:
        return self._DAY_NAME_TO_TEMPLATE.get(day_name, day_name)

    # ── Exercise selection for a template slot ─────────────────────
    _UPPER_MUSCLES = frozenset({
        "chest", "upper_chest", "lats", "mid_back",
        "front_delts", "side_delts", "rear_delts", "biceps", "triceps",
    })
    _LOWER_MUSCLES = frozenset({"quadriceps", "hamstrings", "glutes", "calves"})

    def _muscle_group(self, muscle: str) -> Optional[str]:
        if muscle in self._UPPER_MUSCLES:
            return "upper"
        if muscle in self._LOWER_MUSCLES:
            return "lower"
        return None

    def _apply_override(self, ex: Optional[Exercise], client: ClientProfile) -> Optional[Exercise]:
        """Substitute exercise if the coach has specified a swap for this client."""
        if not ex:
            return None
        overrides = getattr(client, "coach_overrides", None) or {}
        replacement_id = overrides.get(ex.exercise_id)
        if replacement_id:
            replacement = next((e for e in self.exercise_db if e.exercise_id == replacement_id), None)
            if replacement:
                self.last_generation_notes.append(f"override_applied: {ex.exercise_id} → {replacement_id}")
                return replacement
        return ex

    def _select_for_slot(
        self,
        spec: Dict,
        client: ClientProfile,
        used_ids: set,
    ) -> Optional[Exercise]:
        """4-tier fallback: (pattern+muscle) → muscle → (pattern+group) → skip."""
        pattern = spec.get("pattern")
        muscle = spec.get("muscle")
        min_fat = spec.get("min_fat", 1)
        max_fat = spec.get("max_fat", 5)
        slot_type = spec.get("type", "isolation")

        # Powerlifter accessory/isolation slots may pull from the (much larger)
        # powerbuilder pool; only the competition main lift stays powerlifter-only.
        is_main = "main" in slot_type
        is_compound = slot_type in ("main_compound", "secondary_compound")
        if client.avatar == "powerlifter" and not is_main:
            avatars = {"powerlifter", "powerbuilder"}
        else:
            avatars = {client.avatar}

        # ── Ability gate (SP-B1 C5) ────────────────────────────────────────
        # The ladder governs COMPOUND anchor slots only; an isolation slot that carries
        # an anchor pattern must NOT receive the ladder's heavy compound (it keeps its
        # fatigue-bounded selection + the difficulty ceiling).
        from app.domain.workout.ability import LADDERS, client_ability, ladder_rung, global_ability
        if pattern in LADDERS:
            ability = client_ability(client.experience_level, client.exercise_ability, pattern)
            if client.avatar == "powerlifter" and is_main:  # competition mains exempt
                ability = 5
            max_diff = ability   # cap ALL anchor-pattern slots (compound AND isolation)
            # Ladder PICK only for COMPOUND, non-injury-banned slots — an isolation slot
            # tagged with an anchor pattern keeps its fatigue-bounded selection (capped by
            # max_diff); a banned anchor pattern falls to the Tier-5 injury substitution.
            if is_compound and pattern not in self._banned_patterns(client):
                rung_id = ladder_rung(pattern, ability, client.available_equipment)
                if rung_id and rung_id not in used_ids:
                    ex = next((e for e in self.exercise_db if e.exercise_id == rung_id), None)
                    # The ladder pick bypasses _filter_exercises, so re-apply the SAME
                    # safety gates it enforces beyond equipment: avatar match + the
                    # lower_back_pain secondary-muscle guard. If the rung is unsafe, fall
                    # through to the tier fallback (safe + ability-capped via max_diff).
                    if ex and (set(ex.avatar_tags) & avatars) and not (
                        "lower_back_pain" in (client.limitations or [])
                        and "lower_back" in ex.secondary_muscles
                    ):
                        return self._apply_override(ex, client)
        else:
            max_diff = global_ability(client.experience_level)

        def _pick(candidates: List[Exercise]) -> Optional[Exercise]:
            candidates = [c for c in candidates if c.exercise_id not in used_ids]
            if not candidates:
                return None
            return candidates[self._rotation_idx(client.week_number, slot_type, len(candidates))]

        # Tier 1: pattern + muscle
        if pattern and muscle:
            ex = _pick(self._filter_exercises(client, avatars=avatars, pattern=pattern,
                                              primary_muscle=muscle,
                                              min_fatigue=min_fat, max_fatigue=max_fat,
                                              max_difficulty=max_diff))
            if ex:
                return self._apply_override(ex, client)

        # Tier 2: muscle only (drop pattern requirement)
        if muscle:
            ex = _pick(self._filter_exercises(client, avatars=avatars, primary_muscle=muscle,
                                              min_fatigue=min_fat, max_fatigue=max_fat,
                                              max_difficulty=max_diff))
            if ex:
                return self._apply_override(ex, client)

        # Tier 3: pattern + muscle_group (drop specific muscle target)
        if pattern and muscle:
            mg = self._muscle_group(muscle)
            if mg:
                ex = _pick(self._filter_exercises(client, avatars=avatars, pattern=pattern,
                                                  muscle_group=mg,
                                                  min_fatigue=min_fat, max_fatigue=max_fat,
                                                  max_difficulty=max_diff))
                if ex:
                    return self._apply_override(ex, client)

        # Tier 4: last-resort — any exercise for this muscle (or group), dropping
        # fatigue bounds, so a day never ends up empty/thin when SOME option exists.
        # NOTE: difficulty ceiling is preserved (never dropped) even at last-resort.
        if muscle:
            ex = _pick(self._filter_exercises(client, avatars=avatars, primary_muscle=muscle,
                                              max_difficulty=max_diff))
            if ex:
                return self._apply_override(ex, client)
            mg = self._muscle_group(muscle)
            if mg:
                ex = _pick(self._filter_exercises(client, avatars=avatars, muscle_group=mg,
                                                  max_difficulty=max_diff))
                if ex:
                    return self._apply_override(ex, client)

        # Tier 5: injury substitution — the slot's pattern is banned and no safe
        # same-muscle option survived the earlier tiers. Fill the slot with a safe
        # substitute pattern so the day is never left empty.
        if pattern and pattern in self._banned_patterns(client):
            for sub_pat in self._substitute_patterns(client, pattern):
                ex = _pick(self._filter_exercises(client, avatars=avatars, pattern=sub_pat,
                                                  max_difficulty=max_diff))
                if ex:
                    return self._apply_override(ex, client)

        return None

    # ── Slot Filling (template-driven) ────────────────────────────
    def _fill_slots(
        self,
        day_name: str,
        client: ClientProfile,
        budget: Dict[str, int],
        rpe: float,
        prior_week: Optional[WorkoutWeek] = None,
        force_deload: bool = False,
    ) -> WorkoutDay:
        from app.domain.workout.loadseed import seed_working_load
        deload = force_deload or self._is_deload(client.week_number)
        MAX_FATIGUE: int = self._cfg["session"]["max_fatigue"]
        s = self._cfg["sets"]
        r = self._cfg["reps"]
        load_factor: float = self._cfg["periodization"].get("deload_load_factor", 0.6)

        # Resolve template
        templates = self._cfg.get("day_templates", {})
        template_key = self._template_key(day_name)
        slot_specs: List[Dict] = (
            templates.get(template_key)
            or templates.get("Full_Body_A")
            or {"slots": []}
        ).get("slots", [])

        slots: List[WorkoutSlot] = []
        used_ids: set = set()
        current_fatigue = 0
        first_compound_done: List[bool] = [False]

        def _construct_slot(exercise: Exercise, n_sets: int, reps: str, slot_rpe: float, slot_type: str) -> WorkoutSlot:
            pattern = exercise.movement_pattern
            is_compound = exercise.fatigue_cost >= 3

            slot = WorkoutSlot(
                slot_type=slot_type,
                exercise_id=exercise.exercise_id,
                exercise_name=exercise.name,
                sets=n_sets,
                reps=reps,
                rpe=int(slot_rpe),
                rest_seconds=REST_BY_FATIGUE.get(exercise.fatigue_cost, 90),
                tempo=TEMPO_BY_PATTERN.get(pattern),
                coaching_cues=CUES_BY_PATTERN.get(pattern, []),
                warmup_sets=[],
                biomechanical_focus=exercise.biomechanical_focus,
            )

            if prior_week:
                for d in prior_week.days:
                    for prev_slot in d.slots:
                        if prev_slot.exercise_id == exercise.exercise_id and prev_slot.actual_weight is not None:
                            try:
                                slot.target_weight = AutoRegulator.calculate_next_load(
                                    last_weight=float(prev_slot.actual_weight),
                                    last_target_rpe=float(prev_slot.rpe),
                                    last_actual_rpe=float(prev_slot.actual_rpe) if prev_slot.actual_rpe else float(prev_slot.rpe),
                                    next_target_rpe=float(slot_rpe),
                                )
                            except (TypeError, ValueError, AttributeError) as e:
                                logger.warning("load_progression_lookup_failed: %s", e)
                            break
                    else:
                        continue
                    break

            # Week-1 / no-telemetry seeding: if no prior actual set a target_weight,
            # seed a conservative starting load from the client's baseline lifts.
            # The prior-week path above always takes precedence (we only fill a gap).
            if slot.target_weight is None:
                seeded = seed_working_load(client, exercise.movement_pattern, reps, slot_rpe)
                if seeded is not None:
                    slot.target_weight = seeded

            if is_compound:
                is_main = slot_type == "main_compound" and not first_compound_done[0]
                last_top: Optional[float] = None
                if prior_week:
                    for d in prior_week.days:
                        for ps in d.slots:
                            if ps.exercise_id == exercise.exercise_id and ps.actual_weight is not None:
                                last_top = float(ps.actual_weight)
                                break

                try:
                    working_reps = int(reps.split("-")[0])
                except (ValueError, IndexError):
                    working_reps = 5

                raw_warmup = build_warmup(
                    working_load_kg=slot.target_weight if slot.target_weight else 60.0,
                    bar_kg=20.0,
                    working_reps=working_reps,
                    is_compound=True,
                    is_main_lift=is_main,
                    last_top_set_kg=last_top,
                )
                slot.warmup_sets = [WarmupSet(**vars(ws)) for ws in raw_warmup]
                if is_main:
                    first_compound_done[0] = True

            # Caveat-only limitations: warn on affected patterns without excluding.
            for lim in client.limitations:
                spec_cav = INJURY_CAVEATS.get(lim)
                if spec_cav and exercise.movement_pattern in spec_cav["patterns"]:
                    slot.coaching_cues = list(slot.coaching_cues) + [spec_cav["cue"]]

            return slot

        for i, spec in enumerate(slot_specs):
            ex = self._select_for_slot(spec, client, used_ids)
            if ex is None:
                continue
            if current_fatigue + ex.fatigue_cost > MAX_FATIGUE:
                continue

            sets_key = spec["sets"]
            n_sets_raw: int = s.get(sets_key + "_deload" if deload else sets_key,
                                    s.get(sets_key, 3))
            n_sets = self._spend_budget(budget, ex.primary_muscle, n_sets_raw)
            if n_sets <= 0:
                continue

            reps_key = spec["reps"]
            reps_str: str = r.get(reps_key + "_deload" if deload else reps_key,
                                  r.get(reps_key, "8-12"))

            slot = _construct_slot(ex, n_sets, reps_str, rpe, spec["type"])
            slot.slot_order = i + 1
            slot.slot_type = "main_compound" if i == 0 else "secondary_compound" if i == 1 else "isolation"

            if deload and slot.target_weight is not None:
                slot.target_weight = round((slot.target_weight * load_factor) / 2.5) * 2.5

            slots.append(slot)
            used_ids.add(ex.exercise_id)
            current_fatigue += ex.fatigue_cost

        return WorkoutDay(day_name=day_name, slots=slots, total_fatigue=current_fatigue)

    # ── Safety Gates ───────────────────────────────────────────────
    def _check_safety(self, client: ClientProfile) -> None:
        """Raise SafetyRefusalError if any hard-refuse condition is met."""
        if getattr(client, "safety_override_note", None):
            self.last_generation_notes.append(f"safety_gate_skipped: {client.safety_override_note}")
            return  # physician clearance on file — skip gate

        def _refuse(key: str) -> None:
            raise SafetyRefusalError(key, HARD_REFUSE_CONDITIONS[key])

        if (client.systolic_bp is not None) and client.systolic_bp > 160:
            _refuse("systolic_bp_high")

        if client.cardiac_history and client.cardiac_event_weeks_ago is not None:
            if client.cardiac_event_weeks_ago < 24:
                _refuse("recent_cardiac_event")

        if client.pregnancy_status == "1st":
            _refuse("pregnancy_1st_trimester")

        if client.pregnancy_status == "3rd":
            _refuse("pregnancy_3rd_trimester")

        if client.unexplained_weight_loss:
            _refuse("unexplained_weight_loss")

        if client.progressive_neuro_deficits:
            _refuse("progressive_neuro_deficits")

    # ── Orchestrator ───────────────────────────────────────────────
    def generate(self, client: ClientProfile, prior_week: Optional[WorkoutWeek] = None, force_deload: bool = False) -> WorkoutWeek:
        self.last_generation_notes = []
        self._check_safety(client)
        day_templates = self._resolve_split(client.avatar, client.training_days)
        budget = self._budget_volume(client.experience_level)
        rpe = self._calculate_rpe(client.week_number)

        # Deload: reduce total budget
        deload = force_deload or self._is_deload(client.week_number)
        if deload:
            vb = self._cfg["volume_budget"]
            factor: float = vb["deload_factor"]
            min_sets: int = vb["deload_min_sets"]
            budget = {k: max(min_sets, int(v * factor)) for k, v in budget.items()}
            rpe = min(rpe, 6.0)
            trigger = "forced" if force_deload else f"week_{client.week_number}_cycle"
            self.last_generation_notes.append(f"deload_week: RPE={rpe} trigger={trigger}")

        # Per-day budget: split each muscle's weekly cap across the days that train
        # it, so repeated day-types (e.g. 6-day PPL's two Push days) get symmetric
        # volume instead of the first occurrence greedily eating the week's budget
        # and later occurrences collapsing to non-trainable sets.
        import math
        templates_cfg = self._cfg.get("day_templates", {})
        days_training_key: Dict[str, int] = {}
        for day_name in day_templates:
            tk = self._template_key(day_name)
            specs = (templates_cfg.get(tk) or templates_cfg.get("Full_Body_A")
                     or {"slots": []}).get("slots", [])
            seen_keys = set()
            for spec in specs:
                m = spec.get("muscle")
                k = self._budget_key(m) if m else None
                if k:
                    seen_keys.add(k)
            for k in seen_keys:
                days_training_key[k] = days_training_key.get(k, 0) + 1

        days = []
        for day_name in day_templates:
            per_day_budget = {
                k: math.ceil(cap / max(1, days_training_key.get(k, 1)))
                for k, cap in budget.items()
            }
            day = self._fill_slots(day_name, client, per_day_budget, rpe, prior_week, force_deload=deload)
            days.append(day)

        week = WorkoutWeek(week_number=client.week_number, days=days)
        self._validate_volume(week, client.client_id)
        return week

    # ── Volume Validation ──────────────────────────────────────────
    def _validate_volume(self, week: WorkoutWeek, client_id: str) -> None:
        """Log MRV violations and MEV warnings for the generated week."""
        # Build a quick lookup: exercise_id → Exercise
        ex_map = {ex.exercise_id: ex for ex in self.exercise_db}

        # Tally actual sets by budget key
        actual: Dict[str, int] = {k: 0 for k in VOLUME_LANDMARKS}
        for day in week.days:
            for slot in day.slots:
                ex = ex_map.get(slot.exercise_id)
                if ex is None:
                    continue
                key = self._budget_key(ex.primary_muscle)
                if key and key in actual:
                    actual[key] += slot.sets

        for muscle, sets in actual.items():
            if sets == 0:
                continue
            landmarks = VOLUME_LANDMARKS.get(muscle)
            if not landmarks:
                continue
            if sets > landmarks["mrv"]:
                logger.warning(
                    "client=%s muscle=%s sets=%d exceeds MRV=%d — reduce volume",
                    client_id, muscle, sets, landmarks["mrv"],
                )
            elif sets < landmarks["mev"]:
                logger.info(
                    "client=%s muscle=%s sets=%d is below MEV=%d — consider adding volume",
                    client_id, muscle, sets, landmarks["mev"],
                )

        self._check_push_pull_balance(week, client_id)

    def _check_push_pull_balance(self, week: WorkoutWeek, client_id: str) -> None:
        """Warn if weekly push vs pull set counts diverge by more than 20%."""
        push_patterns = {"horizontal_push", "vertical_push"}
        pull_patterns = {"horizontal_pull", "vertical_pull"}
        ex_map = {ex.exercise_id: ex for ex in self.exercise_db}

        push_sets = 0
        pull_sets = 0
        for day in week.days:
            for slot in day.slots:
                ex = ex_map.get(slot.exercise_id)
                if ex is None:
                    continue
                if ex.movement_pattern in push_patterns:
                    push_sets += slot.sets
                elif ex.movement_pattern in pull_patterns:
                    pull_sets += slot.sets

        total = push_sets + pull_sets
        if total == 0:
            return
        ratio = push_sets / pull_sets if pull_sets > 0 else float("inf")
        if ratio > 1.2 or ratio < 0.833:
            logger.warning(
                "client=%s push/pull imbalance — push_sets=%d pull_sets=%d ratio=%.2f",
                client_id, push_sets, pull_sets, ratio,
            )
