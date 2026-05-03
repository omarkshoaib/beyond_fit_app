import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/api/profile_api.dart';
import '../../core/api/sets_api.dart';
import '../../core/models/models.dart';
import '../../core/utils/units.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  UserProfile? _profile;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await ProfileApi.getProfile();
      if (mounted) setState(() { _profile = p; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _logout() async {
    await AuthApi.logout();
    if (mounted) context.go('/login');
  }

  Future<void> _showFeedbackSheet(BuildContext context) async {
    final ctrl = TextEditingController();
    bool sending = false;
    await showModalBottomSheet<void>(
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
              const Text('Send feedback',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              TextField(
                controller: ctrl,
                maxLines: 5,
                autofocus: true,
                decoration: const InputDecoration(
                  hintText: 'What is broken / annoying / awesome?',
                ),
              ),
              const SizedBox(height: 16),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                onPressed: sending
                    ? null
                    : () async {
                        if (ctrl.text.trim().isEmpty) return;
                        setLocal(() => sending = true);
                        try {
                          await FeedbackApi.submit(message: ctrl.text.trim(), appVersion: 'mobile-1.1');
                          if (ctx.mounted) {
                            ScaffoldMessenger.of(ctx).showSnackBar(
                              const SnackBar(content: Text('Thanks — got it.')));
                            Navigator.pop(ctx);
                          }
                        } catch (_) {
                          if (ctx.mounted) {
                            ScaffoldMessenger.of(ctx).showSnackBar(
                              const SnackBar(content: Text('Could not send feedback')));
                            setLocal(() => sending = false);
                          }
                        }
                      },
                child: sending
                    ? const SizedBox(
                        height: 20, width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Text('Send'),
              ),
            ],
          ),
        );
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Profile'),
        actions: [
          TextButton.icon(
            onPressed: _logout,
            icon: const Icon(Icons.logout, size: 18),
            label: const Text('Sign out'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _profile == null
              ? const Center(child: Text('Failed to load profile'))
              : ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    _AvatarHeader(profile: _profile!),
                    const SizedBox(height: 24),
                    _InfoSection(profile: _profile!),
                    const SizedBox(height: 16),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.edit_outlined),
                        title: const Text('Edit Profile'),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () => context.go('/profile/edit'),
                      ),
                    ),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.history),
                        title: const Text('Plan History'),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () => context.go('/plan/history'),
                      ),
                    ),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.refresh),
                        title: const Text('Generate New Plan'),
                        subtitle: const Text('Replace your current plan with a fresh one'),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () async {
                          final messenger = ScaffoldMessenger.of(context);
                          final router = GoRouter.of(context);
                          try {
                            await PlansApi.generate();
                            if (!context.mounted) return;
                            messenger.showSnackBar(const SnackBar(content: Text('New plan generated')));
                            router.go('/home');
                          } catch (_) {
                            messenger.showSnackBar(const SnackBar(content: Text('Could not generate plan')));
                          }
                        },
                      ),
                    ),
                    if (_profile!.isCoach)
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.supervisor_account, color: Colors.blue),
                          title: const Text('Coach Dashboard'),
                          trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                          onTap: () => context.go('/coach'),
                        ),
                      ),
                    if (_profile!.isAdmin)
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.admin_panel_settings, color: Colors.purple),
                          title: const Text('Admin Panel'),
                          trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                          onTap: () => context.go('/admin'),
                        ),
                      ),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.straighten),
                        title: const Text('Weight units'),
                        trailing: SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'kg', label: Text('kg')),
                            ButtonSegment(value: 'lb', label: Text('lb')),
                          ],
                          selected: {Units.current},
                          onSelectionChanged: (s) async {
                            await Units.setUnit(s.first);
                            if (mounted) setState(() {});
                          },
                        ),
                      ),
                    ),
                    Card(
                      child: ListTile(
                        leading: const Icon(Icons.feedback_outlined),
                        title: const Text('Send feedback'),
                        subtitle: const Text('Bug reports, ideas, complaints — we read them all'),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () => _showFeedbackSheet(context),
                      ),
                    ),
                  ],
                ),
    );
  }
}

class _AvatarHeader extends StatelessWidget {
  final UserProfile profile;
  const _AvatarHeader({required this.profile});

  @override
  Widget build(BuildContext context) {
    final initials = (profile.name ?? profile.email).substring(0, 1).toUpperCase();
    return Row(
      children: [
        CircleAvatar(
          radius: 36,
          backgroundColor: Theme.of(context).colorScheme.primary,
          child: Text(initials, style: const TextStyle(fontSize: 28, color: Colors.white, fontWeight: FontWeight.bold)),
        ),
        const SizedBox(width: 16),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(profile.name ?? 'Athlete',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
            Text(profile.email, style: const TextStyle(color: Colors.grey)),
          ],
        ),
      ],
    );
  }
}

class _InfoSection extends StatelessWidget {
  final UserProfile profile;
  const _InfoSection({required this.profile});

  @override
  Widget build(BuildContext context) {
    final avatar = profile.avatar?.replaceAll('_', ' ').toUpperCase() ?? '—';
    final experience = profile.experienceLevel?.toUpperCase() ?? '—';
    final days = profile.trainingDays?.toString() ?? '—';
    final week = profile.weekNumber?.toString() ?? '1';

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            _InfoRow('Training Type', avatar),
            const Divider(height: 24),
            _InfoRow('Experience', experience),
            const Divider(height: 24),
            _InfoRow('Days / Week', days),
            const Divider(height: 24),
            _InfoRow('Current Week', 'Week $week'),
          ],
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  const _InfoRow(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(color: Colors.grey)),
        Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
      ],
    );
  }
}
