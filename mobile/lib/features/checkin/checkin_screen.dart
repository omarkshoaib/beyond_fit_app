import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/checkin_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';

class CheckinScreen extends StatefulWidget {
  const CheckinScreen({super.key});

  @override
  State<CheckinScreen> createState() => _CheckinScreenState();
}

class _CheckinScreenState extends State<CheckinScreen> {
  WorkoutPlan? _plan;
  bool _loading = true;
  bool _submitting = false;

  final Map<int, TextEditingController> _weightCtrl = {};
  final Map<int, TextEditingController> _rpeCtrl = {};
  List<Map<String, dynamic>> _mainSlots = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final plan = await PlansApi.getCurrent();
      final slots = <Map<String, dynamic>>[];
      int idx = 0;
      for (final day in plan.days) {
        for (final slot in (day['slots'] as List? ?? [])) {
          final s = slot as Map<String, dynamic>;
          if (s['slot_type'] == 'main_compound') {
            slots.add({...s, '_idx': idx});
            _weightCtrl[idx] = TextEditingController();
            _rpeCtrl[idx] = TextEditingController();
            idx++;
          }
        }
      }
      if (mounted) setState(() {
        _plan = plan;
        _mainSlots = slots;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    for (final c in _weightCtrl.values) c.dispose();
    for (final c in _rpeCtrl.values) c.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_plan == null) return;

    // Validate all fields filled
    for (final s in _mainSlots) {
      final idx = s['_idx'] as int;
      final w = _weightCtrl[idx]?.text.trim() ?? '';
      final r = _rpeCtrl[idx]?.text.trim() ?? '';
      if (w.isEmpty || r.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Fill in weight and RPE for every lift')),
        );
        return;
      }
      final wNum = double.tryParse(w);
      final rNum = int.tryParse(r);
      if (wNum == null || wNum <= 0) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Weight must be a positive number')),
        );
        return;
      }
      if (rNum == null || rNum < 1 || rNum > 10) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('RPE must be between 1 and 10')),
        );
        return;
      }
    }

    setState(() => _submitting = true);
    try {
      final slots = _mainSlots.map((s) {
        final idx = s['_idx'] as int;
        return {
          'exercise_name': (s['exercise_name'] as String?) ?? '',
          'actual_weight': double.parse(_weightCtrl[idx]!.text),
          'actual_rpe': int.parse(_rpeCtrl[idx]!.text),
        };
      }).toList();
      await CheckinApi.submit(historyId: _plan!.id, slots: slots);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Check-in submitted! Next week\'s plan generating...')),
        );
        context.go('/home');
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Weekly Check-in')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _mainSlots.isEmpty
              ? const Center(child: Text('No main lifts to log. Complete a workout first.'))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Text(
                      'Log your main lifts for Week ${_plan?.weekNumber}',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    const Text('Enter the weight you actually lifted and your perceived exertion (RPE 1-10).',
                        style: TextStyle(color: Colors.grey)),
                    const SizedBox(height: 24),
                    ..._mainSlots.asMap().entries.map((e) {
                      final idx = e.value['_idx'] as int;
                      final name = (e.value['exercise_name'] as String?) ?? 'Exercise';
                      final rpeRaw = e.value['rpe'];
                      return _LiftEntry(
                        name: name,
                        targetWeight: e.value['target_weight'] as num?,
                        targetRpe: rpeRaw is num ? rpeRaw.toInt() : null,
                        weightCtrl: _weightCtrl[idx]!,
                        rpeCtrl: _rpeCtrl[idx]!,
                      );
                    }),
                    const SizedBox(height: 24),
                    ElevatedButton(
                      onPressed: _submitting ? null : _submit,
                      child: _submitting
                          ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Submit Check-in'),
                    ),
                  ],
                ),
    );
  }
}

class _LiftEntry extends StatelessWidget {
  final String name;
  final num? targetWeight;
  final int? targetRpe;
  final TextEditingController weightCtrl;
  final TextEditingController rpeCtrl;

  const _LiftEntry({
    required this.name,
    required this.targetWeight,
    required this.targetRpe,
    required this.weightCtrl,
    required this.rpeCtrl,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            if (targetWeight != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('Target: ${targetWeight}kg @ RPE $targetRpe',
                    style: const TextStyle(color: Colors.grey, fontSize: 13)),
              ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: weightCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Actual weight (kg)'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: rpeCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'RPE (1-10)'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
