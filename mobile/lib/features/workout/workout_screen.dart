import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../core/api/plans_api.dart';
import '../../core/api/sets_api.dart';
import '../../core/models/models.dart';
import '../../core/utils/units.dart';

class WorkoutScreen extends StatefulWidget {
  const WorkoutScreen({super.key});

  @override
  State<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends State<WorkoutScreen> {
  TodaySession? _session;
  WorkoutPlan? _plan;
  bool _loading = true;
  // Track per-set logging state: (slotIndex, setIndex) -> bool
  final Set<String> _loggedSets = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await PlansApi.getToday();
      WorkoutPlan? p;
      try {
        p = await PlansApi.getCurrent();
      } catch (_) {/* no current plan */}
      if (mounted) setState(() {
        _session = s;
        _plan = p;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _markLogged(int slotIdx, int setIdx) {
    setState(() => _loggedSets.add('$slotIdx-$setIdx'));
  }

  bool _isLogged(int slotIdx, int setIdx) => _loggedSets.contains('$slotIdx-$setIdx');

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_session?.dayName ?? "Today's Workout")),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _session == null || _session!.isRestDay
              ? const Center(child: Text('No workout today.'))
              : ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: _session!.slots.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (ctx, i) {
                    final slot = _session!.slots[i] as Map<String, dynamic>;
                    return _SlotCard(
                      slot: slot,
                      index: i,
                      historyId: _plan?.id ?? 0,
                      dayIndex: _session!.dayIndex,
                      isLogged: (setIdx) => _isLogged(i, setIdx),
                      onLogged: (setIdx) => _markLogged(i, setIdx),
                    );
                  },
                ),
    );
  }
}

class _SlotCard extends StatelessWidget {
  final Map<String, dynamic> slot;
  final int index;
  final int historyId;
  final int dayIndex;
  final bool Function(int setIdx) isLogged;
  final void Function(int setIdx) onLogged;

  const _SlotCard({
    required this.slot,
    required this.index,
    required this.historyId,
    required this.dayIndex,
    required this.isLogged,
    required this.onLogged,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final exercise = slot['exercise'] as Map<String, dynamic>? ?? {};
    final name = exercise['name'] as String? ?? 'Exercise ${index + 1}';
    final pattern = exercise['movement_pattern'] as String? ?? '';
    final sets = (slot['sets'] is int) ? slot['sets'] as int : int.tryParse('${slot['sets']}') ?? 3;
    final reps = slot['reps']?.toString() ?? '0';
    final weight = slot['target_weight'] as num?;
    final rpe = slot['rpe'];
    final slotType = slot['slot_type'] as String? ?? '';
    final cue = _cueFor(pattern);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                _SlotBadge(slotType: slotType),
                const Spacer(),
                Text('RPE $rpe', style: const TextStyle(color: Colors.grey, fontSize: 13)),
              ],
            ),
            const SizedBox(height: 8),
            Text(name, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Row(
              children: [
                _StatChip(label: '$sets sets', icon: Icons.repeat),
                const SizedBox(width: 8),
                _StatChip(label: '$reps reps', icon: Icons.fitness_center),
                if (weight != null) ...[
                  const SizedBox(width: 8),
                  _StatChip(label: Units.format(weight), icon: Icons.monitor_weight_outlined),
                ],
              ],
            ),
            if (cue != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    Icon(Icons.lightbulb_outline, size: 16, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Expanded(child: Text(cue, style: const TextStyle(fontSize: 12))),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 12),
            // Per-set log buttons
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: List.generate(sets, (setIdx) {
                final logged = isLogged(setIdx);
                return _SetLogChip(
                  setIndex: setIdx,
                  logged: logged,
                  onTap: logged
                      ? null
                      : () => _showLogSheet(context, setIdx),
                );
              }),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _showLogSheet(BuildContext context, int setIdx) async {
    final repsCtrl = TextEditingController(text: '${slot['reps']}');
    final weightCtrl = TextEditingController(
        text: slot['target_weight'] != null ? Units.fromKg((slot['target_weight'] as num).toDouble()).toString() : '');
    final rpeCtrl = TextEditingController(text: '${slot['rpe'] ?? ''}');

    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
            left: 20, right: 20, top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Log set ${setIdx + 1}',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: repsCtrl,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    decoration: const InputDecoration(labelText: 'Reps'),
                    autofocus: true,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: weightCtrl,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    decoration: InputDecoration(labelText: 'Weight (${Units.current})'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: rpeCtrl,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(labelText: 'RPE (optional, 1-10)'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () async {
                final reps = int.tryParse(repsCtrl.text.trim());
                final weightInput = double.tryParse(weightCtrl.text.trim());
                final rpe = int.tryParse(rpeCtrl.text.trim());
                if (reps == null || reps <= 0 || weightInput == null || weightInput < 0) {
                  ScaffoldMessenger.of(ctx).showSnackBar(
                    const SnackBar(content: Text('Enter valid reps and weight')));
                  return;
                }
                final weightKg = Units.toKg(weightInput);
                try {
                  await SetsApi.log(
                    historyId: historyId,
                    dayIndex: dayIndex,
                    slotIndex: index,
                    setIndex: setIdx,
                    actualReps: reps,
                    actualWeight: weightKg,
                    rpe: rpe,
                  );
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (_) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(
                      const SnackBar(content: Text('Could not save (offline?)')));
                  }
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (ok == true) onLogged(setIdx);
  }
}

class _SetLogChip extends StatelessWidget {
  final int setIndex;
  final bool logged;
  final VoidCallback? onTap;
  const _SetLogChip({required this.setIndex, required this.logged, this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = logged ? Colors.green : theme.colorScheme.primary;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(logged ? Icons.check_circle : Icons.add_circle_outline,
                size: 16, color: color),
            const SizedBox(width: 6),
            Text('Set ${setIndex + 1}',
                style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 13)),
          ],
        ),
      ),
    );
  }
}

String? _cueFor(String pattern) {
  // Mirror constants from app/domain/workout/constants.py:CUES_BY_PATTERN.
  // Keep this in sync if the backend cues change.
  const cues = {
    'squat': 'Brace your core. Drive knees out. Sit between your hips, not in front of them.',
    'hinge': 'Keep the bar close. Hips back, not down. Pull the slack out before you pull.',
    'horizontal_press': 'Set your shoulder blades. Tuck elbows ~45°. Touch where the bar wants to go.',
    'vertical_press': 'Glutes squeezed. Bar moves over the mid-foot. Finish with armpits forward.',
    'horizontal_pull': 'Lead with the elbow. Squeeze at the back. No body english.',
    'vertical_pull': 'Initiate by pulling the shoulder blades down. Drive elbows to the floor.',
    'lunge': 'Hips square. Step long enough that the back knee tracks straight down.',
    'isolation': 'Slow the eccentric. Pause at the lengthened position. Stop one rep shy of failure.',
  };
  return cues[pattern];
}

class _SlotBadge extends StatelessWidget {
  final String slotType;
  const _SlotBadge({required this.slotType});

  @override
  Widget build(BuildContext context) {
    final label = switch (slotType) {
      'main_compound' => 'Main',
      'secondary_compound' => 'Secondary',
      'isolation' => 'Isolation',
      _ => slotType,
    };
    final color = switch (slotType) {
      'main_compound' => Colors.orange,
      'secondary_compound' => Colors.blue,
      _ => Colors.grey,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(label, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
    );
  }
}

class _StatChip extends StatelessWidget {
  final String label;
  final IconData icon;
  const _StatChip({required this.label, required this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: Colors.grey),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(fontSize: 13)),
        ],
      ),
    );
  }
}
