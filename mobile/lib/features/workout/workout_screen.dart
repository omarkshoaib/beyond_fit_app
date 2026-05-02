import 'package:flutter/material.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';

class WorkoutScreen extends StatefulWidget {
  const WorkoutScreen({super.key});

  @override
  State<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends State<WorkoutScreen> {
  TodaySession? _session;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await PlansApi.getToday();
      if (mounted) setState(() { _session = s; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

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
                    return _SlotCard(slot: slot, index: i);
                  },
                ),
    );
  }
}

class _SlotCard extends StatelessWidget {
  final Map<String, dynamic> slot;
  final int index;

  const _SlotCard({required this.slot, required this.index});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final exercise = slot['exercise'] as Map<String, dynamic>? ?? {};
    final name = exercise['name'] as String? ?? 'Exercise ${index + 1}';
    final sets = slot['sets'] as int? ?? 0;
    final reps = slot['reps'] as int? ?? 0;
    final weight = slot['target_weight'] as num?;
    final rpe = slot['rpe'] as int?;
    final slotType = slot['slot_type'] as String? ?? '';

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
                  _StatChip(label: '${weight}kg', icon: Icons.monitor_weight_outlined),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
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
        color: color.withOpacity(0.15),
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
