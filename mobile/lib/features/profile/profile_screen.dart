import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/profile_api.dart';
import '../../core/models/models.dart';

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
                        leading: const Icon(Icons.help_outline),
                        title: const Text('Help & FAQ'),
                        trailing: const Icon(Icons.arrow_forward_ios, size: 14),
                        onTap: () => context.go('/help'),
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
