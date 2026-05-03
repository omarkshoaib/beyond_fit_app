import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/coach_api.dart';
import '../../core/models/models.dart';

class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  UserProfile? _me;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadMe();
  }

  Future<void> _loadMe() async {
    try {
      final me = await AuthApi.me();
      if (mounted) setState(() { _me = me; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final tabs = <Tab>[
      const Tab(icon: Icon(Icons.fitness_center), text: 'Coaches'),
      const Tab(icon: Icon(Icons.people), text: 'Clients'),
      if (_me?.isSuperAdmin == true) const Tab(icon: Icon(Icons.admin_panel_settings), text: 'Admins'),
    ];

    return DefaultTabController(
      length: tabs.length,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Admin Panel'),
          bottom: TabBar(tabs: tabs),
        ),
        body: TabBarView(
          children: [
            const _CoachesTab(),
            const _ClientsTab(),
            if (_me?.isSuperAdmin == true) const _AdminsTab(),
          ],
        ),
      ),
    );
  }
}

// ─── Coaches tab ───────────────────────────────────────────────────────────

class _CoachesTab extends StatefulWidget {
  const _CoachesTab();
  @override
  State<_CoachesTab> createState() => _CoachesTabState();
}

class _CoachesTabState extends State<_CoachesTab> {
  List<Map<String, dynamic>> _coaches = [];
  List<Map<String, dynamic>> _invites = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final coaches = await AdminApi.listCoaches();
      final invites = await AdminApi.listCoachInvites();
      if (mounted) setState(() { _coaches = coaches; _invites = invites; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _showInviteSheet() async {
    final emailCtrl = TextEditingController();
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
            const Text('Invite a coach',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            const Text('They will be activated as a coach automatically when they register with this email.',
                style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            TextField(
              controller: emailCtrl,
              autofocus: true,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Coach email'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () async {
                final email = emailCtrl.text.trim();
                if (email.isEmpty || !email.contains('@')) return;
                try {
                  await AdminApi.inviteCoach(email: email);
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (_) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(
                      const SnackBar(content: Text('Could not send invite')));
                  }
                }
              },
              child: const Text('Send invite'),
            ),
          ],
        ),
      ),
    );
    if (ok == true) _load();
  }

  Future<void> _withdraw(String email) async {
    try {
      await AdminApi.withdrawCoachInvite(email: email);
      _load();
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not withdraw invite')));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showInviteSheet,
        icon: const Icon(Icons.person_add_alt),
        label: const Text('Invite coach'),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_invites.isNotEmpty) ...[
              const Text('PENDING INVITES',
                  style: TextStyle(color: Colors.grey, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1)),
              const SizedBox(height: 8),
              ..._invites.map((inv) => Card(
                    child: ListTile(
                      leading: const Icon(Icons.mail_outline, color: BFColors.signalSoft),
                      title: Text(inv['email'] as String),
                      subtitle: const Text('Awaiting registration'),
                      trailing: IconButton(
                        icon: const Icon(Icons.close, color: BFColors.signal),
                        onPressed: () => _withdraw(inv['email'] as String),
                      ),
                    ),
                  )),
              const SizedBox(height: 16),
            ],
            Text('ACTIVE COACHES (${_coaches.length})',
                style: const TextStyle(color: Colors.grey, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1)),
            const SizedBox(height: 8),
            if (_coaches.isEmpty)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('No coaches yet. Tap "Invite coach" to add one.',
                    style: TextStyle(color: Colors.grey))),
              )
            else
              ..._coaches.map((c) => Card(
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor: Theme.of(context).colorScheme.primary,
                        child: Text(((c['name'] as String?) ?? (c['email'] as String)).substring(0, 1).toUpperCase(),
                            style: const TextStyle(color: BFColors.cream, fontWeight: FontWeight.bold)),
                      ),
                      title: Text((c['name'] as String?) ?? 'Coach'),
                      subtitle: Text(c['email'] as String, style: const TextStyle(color: Colors.grey, fontSize: 12)),
                      trailing: Wrap(
                        spacing: 4,
                        children: [
                          if (c['is_super_admin'] == true) _Pill(label: 'SUPER', color: BFColors.signal),
                          if (c['is_admin'] == true && c['is_super_admin'] != true) _Pill(label: 'ADMIN', color: BFColors.signal),
                        ],
                      ),
                    ),
                  )),
            const SizedBox(height: 80),
          ],
        ),
      ),
    );
  }
}

// ─── Clients tab ───────────────────────────────────────────────────────────

class _ClientsTab extends StatefulWidget {
  const _ClientsTab();
  @override
  State<_ClientsTab> createState() => _ClientsTabState();
}

class _ClientsTabState extends State<_ClientsTab> {
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
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showAssignSheet,
        icon: const Icon(Icons.link),
        label: const Text('Assign client'),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: _clients.length,
          separatorBuilder: (_, __) => const SizedBox(height: 8),
          itemBuilder: (ctx, i) {
            final c = _clients[i];
            return Card(
              child: ListTile(
                title: Text((c['name'] as String?) ?? c['email'] as String),
                subtitle: Text(c['email'] as String,
                    style: const TextStyle(color: Colors.grey, fontSize: 12)),
                trailing: Wrap(
                  spacing: 4,
                  children: [
                    if (c['is_super_admin'] == true) _Pill(label: 'SUPER', color: BFColors.signal),
                    if (c['is_admin'] == true && c['is_super_admin'] != true) _Pill(label: 'ADMIN', color: BFColors.signal),
                    if (c['is_coach'] == true && c['is_admin'] != true) _Pill(label: 'COACH', color: BFColors.signalSoft),
                    if (c['coach_id'] != null) _Pill(label: 'ASSIGNED', color: BFColors.success),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

// ─── Admins tab (super-admin only) ─────────────────────────────────────────

class _AdminsTab extends StatefulWidget {
  const _AdminsTab();
  @override
  State<_AdminsTab> createState() => _AdminsTabState();
}

class _AdminsTabState extends State<_AdminsTab> {
  List<Map<String, dynamic>> _admins = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final list = await AdminApi.listAdmins();
      if (mounted) setState(() { _admins = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _showPromoteSheet() async {
    final emailCtrl = TextEditingController();
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
            const Text('Promote to admin',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            const Text('They must already have a registered account.',
                style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 16),
            TextField(
              controller: emailCtrl,
              autofocus: true,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'User email'),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
              onPressed: () async {
                try {
                  await AdminApi.promoteAdmin(email: emailCtrl.text.trim());
                  if (ctx.mounted) Navigator.pop(ctx, true);
                } catch (_) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(
                      const SnackBar(content: Text('Promotion failed (user must register first)')));
                  }
                }
              },
              child: const Text('Promote'),
            ),
          ],
        ),
      ),
    );
    if (ok == true) _load();
  }

  Future<void> _demote(String email) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Demote $email?'),
        content: const Text('They will lose admin privileges immediately.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: BFColors.signal),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Demote'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      try {
        await AdminApi.demoteAdmin(email: email);
        _load();
      } catch (_) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Demote failed (super-admin cannot be demoted)')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showPromoteSheet,
        icon: const Icon(Icons.upgrade),
        label: const Text('Promote admin'),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: _admins.length,
          separatorBuilder: (_, __) => const SizedBox(height: 8),
          itemBuilder: (ctx, i) {
            final a = _admins[i];
            final isSuper = a['is_super_admin'] == true;
            return Card(
              child: ListTile(
                leading: CircleAvatar(
                  backgroundColor: isSuper ? BFColors.signal : BFColors.signal,
                  child: Icon(
                    isSuper ? Icons.shield : Icons.admin_panel_settings,
                    color: BFColors.cream, size: 20,
                  ),
                ),
                title: Text((a['name'] as String?) ?? a['email'] as String),
                subtitle: Text(a['email'] as String,
                    style: const TextStyle(color: Colors.grey, fontSize: 12)),
                trailing: isSuper
                    ? _Pill(label: 'SUPER', color: BFColors.signal)
                    : IconButton(
                        icon: const Icon(Icons.remove_circle_outline, color: BFColors.signal),
                        onPressed: () => _demote(a['email'] as String),
                      ),
              ),
            );
          },
        ),
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
          style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 10)),
    );
  }
}
