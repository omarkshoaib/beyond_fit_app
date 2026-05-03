import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import 'package:intl/intl.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';

class PlanHistoryScreen extends StatefulWidget {
  const PlanHistoryScreen({super.key});

  @override
  State<PlanHistoryScreen> createState() => _PlanHistoryScreenState();
}

class _PlanHistoryScreenState extends State<PlanHistoryScreen> {
  List<PlanHistoryItem> _history = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final h = await PlansApi.getHistory();
      if (mounted) setState(() { _history = h; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Plan History')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _history.isEmpty
              ? const Center(child: Text('No plans yet.'))
              : ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: _history.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (ctx, i) {
                    final item = _history[i];
                    final date = item.createdAt != null
                        ? DateFormat('MMM d, yyyy').format(DateTime.parse(item.createdAt!))
                        : '—';
                    return Card(
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: item.status == 'active'
                              ? BFColors.success.withOpacity(0.2)
                              : Colors.grey.withOpacity(0.2),
                          child: Text('W${item.weekNumber}',
                              style: TextStyle(
                                  color: item.status == 'active' ? BFColors.success : Colors.grey,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 12)),
                        ),
                        title: Text('Week ${item.weekNumber}'),
                        subtitle: Text(date, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                        trailing: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: item.status == 'active'
                                ? BFColors.success.withOpacity(0.15)
                                : Colors.grey.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            item.status.toUpperCase(),
                            style: TextStyle(
                                color: item.status == 'active' ? BFColors.success : Colors.grey,
                                fontSize: 11,
                                fontWeight: FontWeight.w600),
                          ),
                        ),
                      ),
                    );
                  },
                ),
    );
  }
}
