import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/coach_api.dart';
import '../../core/models/models.dart';

class CoachReviewScreen extends StatefulWidget {
  final String approvalUuid;
  const CoachReviewScreen({super.key, required this.approvalUuid});

  @override
  State<CoachReviewScreen> createState() => _CoachReviewScreenState();
}

class _CoachReviewScreenState extends State<CoachReviewScreen> {
  PendingApproval? _approval;
  bool _loading = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final a = await CoachApi.getPendingDetail(widget.approvalUuid);
      if (mounted) setState(() { _approval = a; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _approve() async {
    setState(() => _busy = true);
    try {
      await CoachApi.approve(widget.approvalUuid);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Plan approved')));
        context.pop();
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Approval failed')));
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _showEditSheet() async {
    final ctrl = TextEditingController();
    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20, right: 20, top: 20,
          bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Edit the plan via LLM',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text(
                'Describe the changes you want. The deterministic engine wrote '
                'the plan; the LLM will mutate it per your direction. You will '
                're-approve afterwards.',
                style: TextStyle(color: Colors.grey, fontSize: 13)),
            const SizedBox(height: 16),
            TextField(
              controller: ctrl,
              maxLines: 4,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'e.g. Drop the deadlift on day 3 and add Romanian deadlifts.',
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Padding(padding: EdgeInsets.all(12), child: Text('Cancel')),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () {
                      if (ctrl.text.trim().isEmpty) return;
                      Navigator.pop(ctx, ctrl.text.trim());
                    },
                    child: const Padding(padding: EdgeInsets.all(12), child: Text('Apply edit')),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
    if (result != null && result.isNotEmpty) {
      setState(() => _busy = true);
      try {
        await CoachApi.editPlan(widget.approvalUuid, result);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Plan updated — review again')));
          await _load();
          if (mounted) setState(() => _busy = false);
        }
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Edit failed')));
          setState(() => _busy = false);
        }
      }
    }
  }

  Future<void> _showRejectSheet() async {
    final ctrl = TextEditingController();
    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
          left: 20, right: 20, top: 20,
          bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Send feedback',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text('Tell the client what to adjust.',
                style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            TextField(
              controller: ctrl,
              maxLines: 4,
              autofocus: true,
              decoration: const InputDecoration(
                hintText: 'e.g. Too much volume on day 3, please reduce.',
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('Cancel'),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton(
                    onPressed: () {
                      if (ctrl.text.trim().isEmpty) return;
                      Navigator.pop(ctx, ctrl.text.trim());
                    },
                    style: FilledButton.styleFrom(backgroundColor: BFColors.signal),
                    child: const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('Send'),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );

    if (result != null && result.isNotEmpty) {
      setState(() => _busy = true);
      try {
        await CoachApi.reject(widget.approvalUuid, result);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Feedback sent to client')));
          context.pop();
        }
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Could not send feedback')));
          setState(() => _busy = false);
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Review Plan')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _approval == null
              ? const Center(child: Text('Approval not found'))
              : Column(
                  children: [
                    Expanded(
                      child: ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          Card(
                            child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Row(
                                children: [
                                  CircleAvatar(
                                    backgroundColor: theme.colorScheme.primary,
                                    child: Text(
                                      _approval!.clientName.substring(0, 1).toUpperCase(),
                                      style: const TextStyle(color: BFColors.cream, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(_approval!.clientName,
                                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                                        Text(_approval!.clientEmail,
                                            style: TextStyle(color: Colors.grey.shade400, fontSize: 12)),
                                      ],
                                    ),
                                  ),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: theme.colorScheme.primary.withValues(alpha: 0.15),
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    child: Text(
                                      'Week ${_approval!.weekNumber}',
                                      style: TextStyle(
                                          color: theme.colorScheme.primary,
                                          fontWeight: FontWeight.w600,
                                          fontSize: 12),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          const SizedBox(height: 16),
                          ..._approval!.days.map((d) => _DayCard(day: d as Map<String, dynamic>)),
                        ],
                      ),
                    ),
                    SafeArea(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: OutlinedButton.icon(
                                    style: OutlinedButton.styleFrom(
                                      minimumSize: const Size.fromHeight(54),
                                      side: BorderSide(color: BFColors.signal),
                                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                                    ),
                                    onPressed: _busy ? null : _showRejectSheet,
                                    icon: Icon(Icons.close, color: BFColors.signal),
                                    label: Text('Reject', style: TextStyle(color: BFColors.signal)),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: FilledButton.icon(
                                    style: FilledButton.styleFrom(
                                      minimumSize: const Size.fromHeight(54),
                                      backgroundColor: BFColors.success,
                                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                                    ),
                                    onPressed: _busy ? null : _approve,
                                    icon: _busy
                                        ? const SizedBox(
                                            height: 18, width: 18,
                                            child: CircularProgressIndicator(strokeWidth: 2, color: BFColors.cream))
                                        : const Icon(Icons.check),
                                    label: const Text('Approve', style: TextStyle(fontWeight: FontWeight.w600)),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            TextButton.icon(
                              onPressed: _busy ? null : _showEditSheet,
                              icon: const Icon(Icons.edit_note, size: 20),
                              label: const Text('Edit plan via LLM before approving'),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
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
      margin: const EdgeInsets.only(bottom: 10),
      child: ExpansionTile(
        title: Text(dayName, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text('${slots.length} exercises',
            style: TextStyle(color: Colors.grey.shade400, fontSize: 12)),
        children: slots.map((s) {
          final slot = s as Map<String, dynamic>;
          // WorkoutSlot serializes flat: exercise_name, exercise_id, sets, reps, rpe.
          final name = slot['exercise_name'] as String? ?? '?';
          final sets = slot['sets']?.toString() ?? '?';
          final reps = slot['reps']?.toString() ?? '?';
          final weight = slot['target_weight'];
          final rpe = slot['rpe'];
          return ListTile(
            dense: true,
            title: Text(name),
            subtitle: Text(
              '$sets × $reps${weight != null ? " @ ${weight}kg" : ""} • RPE $rpe',
              style: TextStyle(color: Colors.grey.shade400, fontSize: 12),
            ),
          );
        }).toList(),
      ),
    );
  }
}
