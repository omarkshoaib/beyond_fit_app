import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/auth_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/api/profile_api.dart';
import '../../core/api/sets_api.dart';
import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/units.dart';
import '../../core/widgets/editorial.dart';

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
      backgroundColor: BFColors.ink,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
      builder: (ctx) => StatefulBuilder(builder: (ctx, setLocal) {
        return Padding(
          padding: EdgeInsets.only(
              left: 24, right: 24, top: 24,
              bottom: MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionLabel(number: '01', label: 'Feedback'),
              const SizedBox(height: 12),
              Text('Send a note', style: Theme.of(context).textTheme.displaySmall),
              const SizedBox(height: 16),
              TextField(
                controller: ctrl,
                maxLines: 5,
                autofocus: true,
                style: GoogleFonts.crimsonPro(fontSize: 16, color: BFColors.cream),
                decoration: const InputDecoration(
                  hintText: 'What is broken / annoying / awesome?',
                ),
              ),
              const SizedBox(height: 20),
              EditorialPrimaryButton(
                label: 'Send',
                busy: sending,
                onPressed: sending ? null : () async {
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
      body: Stack(
        children: [
          const PaperGrain(opacity: 0.04),
          Positioned(top: 0, left: 0, right: 0, child: Container(height: 4, color: BFColors.signal)),
          SafeArea(
            child: _loading
                ? const Center(child: CircularProgressIndicator(strokeWidth: 1.4))
                : _profile == null
                    ? const Center(child: Text('Failed to load profile'))
                    : ListView(
                        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
                        children: [
                          Row(
                            children: [
                              IconButton(
                                icon: const Icon(Icons.arrow_back),
                                onPressed: () => context.go('/home'),
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints(),
                              ),
                              const SizedBox(width: 8),
                              Text('PROFILE',
                                  style: GoogleFonts.jetBrainsMono(
                                    fontSize: 10, color: BFColors.creamMute,
                                    fontWeight: FontWeight.w500, letterSpacing: 1.8,
                                  )),
                              const Spacer(),
                              TextButton.icon(
                                onPressed: _logout,
                                icon: const Icon(Icons.logout, size: 14),
                                label: const Text('SIGN OUT'),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          _AvatarHeader(profile: _profile!),
                          const SizedBox(height: 24),
                          if (_profile!.isSuperAdmin)
                            _RolePill(label: 'SUPER · ADMIN', color: BFColors.signal),
                          if (_profile!.isAdmin && !_profile!.isSuperAdmin)
                            _RolePill(label: 'ADMIN', color: BFColors.signalSoft),
                          if (_profile!.isCoach && !_profile!.isAdmin)
                            _RolePill(label: 'COACH', color: BFColors.signalSoft),
                          const SizedBox(height: 24),
                          const RuledLine(leadLabel: '§·01'),
                          const SizedBox(height: 16),
                          _InfoSection(profile: _profile!),
                          const SizedBox(height: 28),
                          const RuledLine(leadLabel: '§·02'),
                          const SizedBox(height: 12),
                          SectionLabel(number: '02', label: 'Actions'),
                          const SizedBox(height: 14),
                          _MenuTile(
                            number: '01', label: 'Edit profile',
                            icon: Icons.edit_outlined,
                            onTap: () => context.go('/profile/edit'),
                          ),
                          _MenuTile(
                            number: '02', label: 'Plan history',
                            icon: Icons.history,
                            onTap: () => context.go('/plan/history'),
                          ),
                          _MenuTile(
                            number: '03', label: 'Generate new plan',
                            sub: 'Replace your current plan with a fresh one',
                            icon: Icons.refresh,
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
                          if (_profile!.isCoach)
                            _MenuTile(
                              number: '04', label: 'Coach dashboard',
                              icon: Icons.supervisor_account,
                              accent: BFColors.signal,
                              onTap: () => context.go('/coach'),
                            ),
                          if (_profile!.isAdmin)
                            _MenuTile(
                              number: '05', label: 'Admin panel',
                              icon: Icons.admin_panel_settings,
                              accent: BFColors.signal,
                              onTap: () => context.go('/admin'),
                            ),
                          const SizedBox(height: 28),
                          const RuledLine(leadLabel: '§·03'),
                          const SizedBox(height: 12),
                          SectionLabel(number: '03', label: 'Preferences'),
                          const SizedBox(height: 14),
                          RuledCard(
                            padding: const EdgeInsets.fromLTRB(18, 14, 14, 14),
                            child: Row(
                              children: [
                                const Icon(Icons.straighten, size: 20, color: BFColors.creamSoft),
                                const SizedBox(width: 14),
                                Expanded(
                                  child: Text('Weight units',
                                      style: GoogleFonts.crimsonPro(
                                        fontSize: 16, color: BFColors.cream,
                                        fontWeight: FontWeight.w500,
                                      )),
                                ),
                                SegmentedButton<String>(
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
                              ],
                            ),
                          ),
                          const SizedBox(height: 10),
                          _MenuTile(
                            number: '06', label: 'Send feedback',
                            sub: 'Bug reports, ideas, complaints — we read them all',
                            icon: Icons.feedback_outlined,
                            onTap: () => _showFeedbackSheet(context),
                          ),
                        ],
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
        Container(
          width: 72, height: 72,
          decoration: BoxDecoration(
            border: Border.all(color: BFColors.signal, width: 1.5),
            color: BFColors.inkSoft,
          ),
          alignment: Alignment.center,
          child: Text(
            initials,
            style: GoogleFonts.fraunces(
              fontSize: 36, color: BFColors.cream,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(width: 18),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                profile.name ?? 'Athlete',
                style: GoogleFonts.fraunces(
                  fontSize: 26, color: BFColors.cream,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.6,
                ),
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(
                profile.email,
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 11, color: BFColors.creamMute,
                  fontWeight: FontWeight.w400, letterSpacing: 0.6,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _RolePill extends StatelessWidget {
  final String label;
  final Color color;
  const _RolePill({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      margin: const EdgeInsets.only(top: 4),
      decoration: BoxDecoration(border: Border.all(color: color, width: 1)),
      child: Text(
        label,
        style: GoogleFonts.jetBrainsMono(
          fontSize: 9, color: color,
          fontWeight: FontWeight.w700, letterSpacing: 2,
        ),
      ),
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

    return RuledCard(
      child: Column(
        children: [
          _InfoRow('Training type', avatar),
          const Divider(height: 24),
          _InfoRow('Experience', experience),
          const Divider(height: 24),
          _InfoRow('Days / week', days),
          const Divider(height: 24),
          _InfoRow('Current week', 'Week $week'),
        ],
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
        Text(label.toUpperCase(),
            style: GoogleFonts.jetBrainsMono(
              fontSize: 10, color: BFColors.creamMute,
              fontWeight: FontWeight.w500, letterSpacing: 1.6,
            )),
        Text(value,
            style: GoogleFonts.crimsonPro(
              fontSize: 15, color: BFColors.cream,
              fontWeight: FontWeight.w600,
            )),
      ],
    );
  }
}

class _MenuTile extends StatelessWidget {
  final String number;
  final String label;
  final String? sub;
  final IconData icon;
  final VoidCallback onTap;
  final Color? accent;

  const _MenuTile({
    required this.number,
    required this.label,
    required this.icon,
    required this.onTap,
    this.sub,
    this.accent,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: RuledCard(
        onTap: onTap,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        child: Row(
          children: [
            Text(
              number,
              style: GoogleFonts.fraunces(
                fontSize: 22, color: accent ?? BFColors.signal,
                fontStyle: FontStyle.italic, fontWeight: FontWeight.w400,
              ),
            ),
            const SizedBox(width: 14),
            Icon(icon, size: 18, color: accent ?? BFColors.creamSoft),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(label,
                      style: GoogleFonts.crimsonPro(
                        fontSize: 16, color: BFColors.cream,
                        fontWeight: FontWeight.w500,
                      )),
                  if (sub != null) ...[
                    const SizedBox(height: 2),
                    Text(sub!,
                        style: GoogleFonts.crimsonPro(
                          fontSize: 12, color: BFColors.creamMute,
                          fontStyle: FontStyle.italic,
                        ),
                        overflow: TextOverflow.ellipsis),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.arrow_forward, size: 14, color: BFColors.creamMute),
          ],
        ),
      ),
    );
  }
}
