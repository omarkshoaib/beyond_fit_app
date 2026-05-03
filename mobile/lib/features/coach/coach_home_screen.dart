import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/coach_api.dart';
import '../../core/models/models.dart';
import '../../core/widgets/friendly_error.dart';

class CoachHomeScreen extends StatefulWidget {
  const CoachHomeScreen({super.key});

  @override
  State<CoachHomeScreen> createState() => _CoachHomeScreenState();
}

class _CoachHomeScreenState extends State<CoachHomeScreen> {
  UserProfile? _me;
  List<CoachClient> _clients = [];
  List<PendingApproval> _pending = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await AuthApi.me();
      final clients = await CoachApi.listClients();
      final pending = await CoachApi.listPending();
      if (mounted) {
        setState(() {
          _me = me;
          _clients = clients;
          _pending = pending;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Could not load coach dashboard.';
          _loading = false;
        });
      }
    }
  }

  Future<void> _logout() async {
    await AuthApi.logout();
    if (mounted) context.go('/login');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        toolbarHeight: 72,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Coach',
              style: TextStyle(fontSize: 13, color: Colors.grey.shade400, fontWeight: FontWeight.w400),
            ),
            Text(_me?.name ?? 'Coach', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          ],
        ),
        actions: [
          IconButton(icon: const Icon(Icons.logout), onPressed: _logout),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? FriendlyState(
                  icon: Icons.cloud_off,
                  title: 'Connection issue',
                  message: _error!,
                  actionLabel: 'Retry',
                  onAction: _load,
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (_pending.isNotEmpty) ...[
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                              decoration: BoxDecoration(
                                color: Colors.orange.withValues(alpha: 0.18),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Text(
                                '${_pending.length} pending',
                                style: const TextStyle(
                                  color: Colors.orange,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                            const Spacer(),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text('Awaiting your review',
                            style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                        const SizedBox(height: 8),
                        ..._pending.map((p) => _PendingCard(approval: p, onTap: () async {
                              await context.push('/coach/review/${p.approvalUuid}');
                              _load();
                            })),
                        const SizedBox(height: 24),
                      ],
                      Text('Your clients (${_clients.length})',
                          style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      if (_clients.isEmpty)
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(
                            'No clients assigned yet. The admin needs to assign clients to you.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.grey.shade400),
                          ),
                        )
                      else
                        ..._clients.map((c) => _ClientTile(client: c)),
                    ],
                  ),
                ),
    );
  }
}

class _PendingCard extends StatelessWidget {
  final PendingApproval approval;
  final VoidCallback onTap;

  const _PendingCard({required this.approval, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: Theme.of(context).colorScheme.surfaceContainerHighest,
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: Colors.orange.withValues(alpha: 0.2),
          child: const Icon(Icons.fact_check_outlined, color: Colors.orange, size: 20),
        ),
        title: Text(approval.clientName, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text('Week ${approval.weekNumber} • ${approval.days.length} days',
            style: TextStyle(color: Colors.grey.shade400, fontSize: 12)),
        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
        onTap: onTap,
      ),
    );
  }
}

class _ClientTile extends StatelessWidget {
  final CoachClient client;
  const _ClientTile({required this.client});

  @override
  Widget build(BuildContext context) {
    final initials = (client.name ?? client.email).substring(0, 1).toUpperCase();
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: Theme.of(context).colorScheme.primary,
          child: Text(initials, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        ),
        title: Text(client.name ?? 'Client',
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(
          [
            if (client.experienceLevel != null) client.experienceLevel!.toUpperCase(),
            'Week ${client.weekNumber ?? 1}',
            '${client.trainingDays ?? 3} days/wk',
          ].join(' • '),
          style: TextStyle(color: Colors.grey.shade400, fontSize: 12),
        ),
        trailing: client.pendingCount > 0
            ? Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: Colors.orange,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text('${client.pendingCount}',
                    style: const TextStyle(
                        color: Colors.white, fontWeight: FontWeight.bold, fontSize: 12)),
              )
            : const Icon(Icons.arrow_forward_ios, size: 14, color: Colors.grey),
      ),
    );
  }
}
