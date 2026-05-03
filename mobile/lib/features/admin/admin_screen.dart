import 'package:flutter/material.dart';
import '../../core/api/coach_api.dart';

class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  List<Map<String, dynamic>> _clients = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await AdminApi.listClients();
      if (mounted) setState(() { _clients = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _showPromoteSheet() async {
    final emailCtrl = TextEditingController();
    bool isAdmin = false;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Theme.of(context).colorScheme.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(builder: (ctx, setLocal) {
        return Padding(
          padding: EdgeInsets.only(
              left: 20, right: 20, top: 20,
              bottom: MediaQuery.of(ctx).viewInsets.bottom + 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Promote a user', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              TextField(
                controller: emailCtrl,
                autofocus: true,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'User email'),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: isAdmin,
                onChanged: (v) => setLocal(() => isAdmin = v ?? false),
                title: const Text('Also grant admin privileges'),
              ),
              const SizedBox(height: 16),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                onPressed: () async {
                  if (emailCtrl.text.trim().isEmpty) return;
                  try {
                    await AdminApi.promoteCoach(
                        email: emailCtrl.text.trim(), isCoach: true, isAdmin: isAdmin);
                    if (ctx.mounted) Navigator.pop(ctx, true);
                  } catch (_) {
                    if (ctx.mounted) {
                      ScaffoldMessenger.of(ctx).showSnackBar(
                        const SnackBar(content: Text('User not found')));
                    }
                  }
                },
                child: const Text('Promote to Coach'),
              ),
            ],
          ),
        );
      }),
    );
    if (ok == true) _load();
  }

  Future<void> _showAssignSheet() async {
    final clientCtrl = TextEditingController();
    final coachCtrl = TextEditingController();
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
            const Text('Assign client to coach',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            TextField(
              controller: clientCtrl,
              autofocus: true,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Client email'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: coachCtrl,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Coach email'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () async {
                try {
                  await AdminApi.assignClientToCoach(
                    clientEmail: clientCtrl.text.trim(),
                    coachEmail: coachCtrl.text.trim(),
                  );
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (_) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(
                      const SnackBar(content: Text('Assignment failed')));
                  }
                }
              },
              child: const Text('Assign'),
            ),
          ],
        ),
      ),
    );
    if (ok == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin Panel'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _showPromoteSheet,
                          icon: const Icon(Icons.upgrade),
                          label: const Text('Promote Coach'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: FilledButton.icon(
                          onPressed: _showAssignSheet,
                          icon: const Icon(Icons.link),
                          label: const Text('Assign Client'),
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    itemCount: _clients.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (ctx, i) {
                      final c = _clients[i];
                      final isCoach = c['is_coach'] as bool? ?? false;
                      final isAdmin = c['is_admin'] as bool? ?? false;
                      return Card(
                        child: ListTile(
                          title: Text(c['name'] as String? ?? c['email'] as String),
                          subtitle: Text(c['email'] as String,
                              style: const TextStyle(color: Colors.grey, fontSize: 12)),
                          trailing: Wrap(
                            spacing: 4,
                            children: [
                              if (isAdmin) _Pill(label: 'ADMIN', color: Colors.purple),
                              if (isCoach) _Pill(label: 'COACH', color: Colors.blue),
                              if (c['coach_id'] != null) _Pill(label: 'ASSIGNED', color: Colors.green),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
    );
  }
}

class _Pill extends StatelessWidget {
  final String label;
  final Color color;
  const _Pill({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.18),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(label,
          style: TextStyle(
              color: color, fontWeight: FontWeight.bold, fontSize: 10)),
    );
  }
}
