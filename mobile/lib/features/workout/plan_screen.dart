import 'package:flutter/material.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';

class PlanScreen extends StatefulWidget {
  const PlanScreen({super.key});

  @override
  State<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends State<PlanScreen> {
  WorkoutPlan? _plan;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await PlansApi.getCurrent();
      if (mounted) setState(() { _plan = p; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Full Plan')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _plan == null
              ? const Center(child: Text('No active plan. Complete onboarding to get started.'))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    _PlanHeader(plan: _plan!),
                    const SizedBox(height: 16),
                    ..._plan!.days.map((day) {
                      final d = day as Map<String, dynamic>;
                      return _DayCard(day: d);
                    }),
                  ],
                ),
    );
  }
}

class _PlanHeader extends StatelessWidget {
  final WorkoutPlan plan;
  const _PlanHeader({required this.plan});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Week ${plan.weekNumber}', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
            Text('Block ${plan.blockNumber}', style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 8),
            Text('${plan.days.length} training days', style: const TextStyle(color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}

class _DayCard extends StatelessWidget {
  final Map<String, dynamic> day;
  const _DayCard({required this.day});

  @override
  Widget build(BuildContext context) {
    final dayName = day['day_name'] as String? ?? 'Day';
    final slots = (day['slots'] as List?) ?? [];

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ExpansionTile(
        title: Text(dayName, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text('${slots.length} exercises', style: const TextStyle(color: Colors.grey, fontSize: 12)),
        children: slots.map((s) {
          final slot = s as Map<String, dynamic>;
          final exercise = slot['exercise'] as Map? ?? {};
          final name = exercise['name'] as String? ?? '?';
          final sets = slot['sets'];
          final reps = slot['reps'];
          final weight = slot['target_weight'];
          return ListTile(
            dense: true,
            title: Text(name),
            subtitle: Text('$sets × $reps${weight != null ? " @ ${weight}kg" : ""}',
                style: const TextStyle(color: Colors.grey)),
          );
        }).toList(),
      ),
    );
  }
}
