import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/auth_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/editorial.dart';
import '../../core/widgets/friendly_error.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  UserProfile? _profile;
  TodaySession? _today;
  bool _loading = true;
  bool _generating = false;
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
      final profile = await AuthApi.me();
      final today = await PlansApi.getToday();
      if (mounted) {
        setState(() {
          _profile = profile;
          _today = today;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Could not load your dashboard. Check your connection.';
          _loading = false;
        });
      }
    }
  }

  Future<void> _generateFirstPlan() async {
    setState(() => _generating = true);
    try {
      await PlansApi.generate();
      await _load();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not generate plan. Try again.')),
        );
        setState(() => _generating = false);
      }
    }
  }

  String _greeting() {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning,';
    if (hour < 18) return 'Good afternoon,';
    return 'Good evening,';
  }

  @override
  Widget build(BuildContext context) {
    final name = _profile?.name?.split(' ').first ?? 'Athlete';

    return Scaffold(
      body: Stack(
        children: [
          const PaperGrain(opacity: 0.04),
          Positioned(top: 0, left: 0, right: 0, child: Container(height: 4, color: BFColors.signal)),
          SafeArea(
            child: Column(
              children: [
                _Topbar(name: name, onProfileTap: () => context.go('/profile')),
                Expanded(child: _buildBody(name)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(String name) {
    if (_loading) return const Center(child: CircularProgressIndicator(strokeWidth: 1.4));

    if (_error != null) {
      return FriendlyState(
        icon: Icons.cloud_off,
        title: 'Connection issue',
        message: _error!,
        actionLabel: 'Retry',
        onAction: _load,
      );
    }

    if (_today?.pendingReview == true) {
      return FriendlyState(
        icon: Icons.fact_check_outlined,
        title: 'Plan under review',
        message: 'Your coach is reviewing your plan. You will see it here as soon as it is approved.',
        actionLabel: 'Refresh',
        onAction: _load,
        iconColor: BFColors.signalSoft,
      );
    }

    if (_today?.rejectionFeedback != null && _today!.rejectionFeedback!.isNotEmpty) {
      return FriendlyState(
        icon: Icons.feedback_outlined,
        title: 'Coach feedback',
        message:
            '"${_today!.rejectionFeedback}"\n\nGenerate a new plan to apply your coach\'s feedback.',
        actionLabel: _generating ? 'Generating…' : 'Generate New Plan',
        onAction: _generating ? null : _generateFirstPlan,
        iconColor: BFColors.signalSoft,
      );
    }

    if (_today?.noPlan == true) {
      return FriendlyState(
        icon: Icons.flag_outlined,
        title: 'Ready to start?',
        message: 'Generate your first deterministic training plan based on your profile.',
        actionLabel: _generating ? 'Generating…' : 'Generate My Plan',
        onAction: _generating ? null : _generateFirstPlan,
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      color: BFColors.signal,
      backgroundColor: BFColors.inkSoft,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        children: [
          if (_profile != null && !_profile!.isVerified) ...[
            _UnverifiedBanner(email: _profile!.email),
            const SizedBox(height: 18),
          ],

          // Greeting block — Fraunces displayMedium with italic name
          Text(_greeting(),
              style: GoogleFonts.crimsonPro(
                fontSize: 16, fontStyle: FontStyle.italic,
                color: BFColors.creamMute,
              )),
          const SizedBox(height: 4),
          Text.rich(
            TextSpan(children: [
              TextSpan(text: '$name.', style: Theme.of(context).textTheme.displayMedium),
            ]),
          ),
          const SizedBox(height: 24),

          // Week numeral + side meta row
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              NumeralStat(
                value: '${_profile?.weekNumber ?? 1}',
                label: 'Week',
                size: 64,
              ),
              const SizedBox(width: 24),
              Container(width: 1, height: 56, color: BFColors.inkRule),
              const SizedBox(width: 24),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      (_profile?.experienceLevel ?? 'beginner').toUpperCase(),
                      style: GoogleFonts.jetBrainsMono(
                        fontSize: 10, color: BFColors.cream,
                        fontWeight: FontWeight.w600, letterSpacing: 2,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${_profile?.trainingDays ?? 3} days/wk',
                      style: GoogleFonts.crimsonPro(
                        fontSize: 14, fontStyle: FontStyle.italic,
                        color: BFColors.creamSoft,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),

          const SizedBox(height: 28),
          const RuledLine(leadLabel: '§·02'),
          const SizedBox(height: 14),
          SectionLabel(number: '02', label: "Today's session"),
          const SizedBox(height: 14),
          _TodayCard(session: _today!),

          const SizedBox(height: 28),
          const RuledLine(leadLabel: '§·03'),
          const SizedBox(height: 14),
          SectionLabel(number: '03', label: 'Quick actions'),
          const SizedBox(height: 14),
          const _QuickActions(),
        ],
      ),
    );
  }
}

class _Topbar extends StatelessWidget {
  final String name;
  final VoidCallback onProfileTap;
  const _Topbar({required this.name, required this.onProfileTap});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      decoration: const Border(bottom: BorderSide(color: BFColors.inkRule)).toBoxDecoration(),
      child: Row(
        children: [
          // Mini brand mark
          Text(
            'beyond',
            style: GoogleFonts.fraunces(
              fontSize: 18, color: BFColors.cream,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.6,
            ),
          ),
          Text('&',
              style: BFType.ital(size: 18, color: BFColors.signal, weight: FontWeight.w400)),
          Text(
            'fit',
            style: GoogleFonts.fraunces(
              fontSize: 18, color: BFColors.cream,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.6,
            ),
          ),
          const Spacer(),
          // Date stamp, monospace
          Text(
            _formatToday(),
            style: GoogleFonts.jetBrainsMono(
              fontSize: 10, color: BFColors.creamMute,
              fontWeight: FontWeight.w500, letterSpacing: 1.6,
            ),
          ),
          const SizedBox(width: 16),
          GestureDetector(
            onTap: onProfileTap,
            child: Container(
              width: 34, height: 34,
              decoration: BoxDecoration(
                border: Border.all(color: BFColors.signal, width: 1),
                color: BFColors.inkSoft,
              ),
              alignment: Alignment.center,
              child: Text(
                name.substring(0, 1).toUpperCase(),
                style: GoogleFonts.fraunces(
                  fontSize: 16, color: BFColors.cream,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _formatToday() {
    final now = DateTime.now();
    const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
    return '${now.day.toString().padLeft(2, '0')} ${months[now.month - 1]} ${now.year}';
  }
}

extension _BorderBox on Border {
  BoxDecoration toBoxDecoration() => BoxDecoration(border: this);
}

class _UnverifiedBanner extends StatefulWidget {
  final String email;
  const _UnverifiedBanner({required this.email});

  @override
  State<_UnverifiedBanner> createState() => _UnverifiedBannerState();
}

class _UnverifiedBannerState extends State<_UnverifiedBanner> {
  bool _sending = false;
  bool _sent = false;

  Future<void> _resend() async {
    setState(() => _sending = true);
    try {
      await AuthApi.resendVerification();
      if (mounted) setState(() { _sent = true; _sending = false; });
    } catch (_) {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
      decoration: BoxDecoration(
        color: BFColors.signalSoft.withValues(alpha: 0.10),
        border: Border.all(color: BFColors.signalSoft.withValues(alpha: 0.45)),
      ),
      child: Row(
        children: [
          const Icon(Icons.mark_email_unread_outlined,
              color: BFColors.signalSoft, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              _sent ? 'Verification sent to ${widget.email}' : 'Verify your email to secure your account',
              style: GoogleFonts.crimsonPro(
                fontSize: 14, color: BFColors.cream, fontWeight: FontWeight.w500,
              ),
            ),
          ),
          if (!_sent)
            TextButton(
              onPressed: _sending ? null : _resend,
              style: TextButton.styleFrom(foregroundColor: BFColors.signalSoft),
              child: _sending
                  ? const SizedBox(
                      width: 14, height: 14,
                      child: CircularProgressIndicator(strokeWidth: 1.4, color: BFColors.signalSoft))
                  : const Text('RESEND'),
            ),
        ],
      ),
    );
  }
}

class _TodayCard extends StatelessWidget {
  final TodaySession session;
  const _TodayCard({required this.session});

  @override
  Widget build(BuildContext context) {
    if (session.isRestDay) {
      return RuledCard(
        padding: const EdgeInsets.all(28),
        child: Column(
          children: [
            const Icon(Icons.hotel, size: 48, color: BFColors.creamSoft),
            const SizedBox(height: 16),
            Text('Rest Day', style: Theme.of(context).textTheme.headlineMedium),
            const SizedBox(height: 8),
            Text('Recovery is part of training.',
                style: GoogleFonts.crimsonPro(
                  fontSize: 15, fontStyle: FontStyle.italic,
                  color: BFColors.creamSoft,
                )),
          ],
        ),
      );
    }

    return RuledCard(
      onTap: () => GoRouter.of(context).go('/workout'),
      padding: const EdgeInsets.fromLTRB(22, 22, 22, 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                'TODAY · DAY ${session.dayIndex + 1} OF ${session.totalDays}',
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 9, color: BFColors.creamMute,
                  fontWeight: FontWeight.w500, letterSpacing: 1.8,
                ),
              ),
              const Spacer(),
              const Icon(Icons.arrow_forward, size: 14, color: BFColors.creamMute),
            ],
          ),
          const SizedBox(height: 14),
          // Day name in display Fraunces with italic mid-word
          Text(
            session.dayName,
            style: GoogleFonts.fraunces(
              fontSize: 38, height: 0.95, color: BFColors.cream,
              fontWeight: FontWeight.w500,
              letterSpacing: -1.0,
            ),
          ),
          const SizedBox(height: 18),
          // Stat row: exercise count + duration
          Row(
            children: [
              _MiniStat(value: '${session.slots.length}', label: 'exercises'),
              const SizedBox(width: 28),
              _MiniStat(value: '~60', label: 'minutes'),
            ],
          ),
          const SizedBox(height: 22),
          EditorialPrimaryButton(
            label: 'Start workout',
            icon: Icons.play_arrow_rounded,
            onPressed: () => GoRouter.of(context).go('/workout'),
          ),
        ],
      ),
    );
  }
}

class _MiniStat extends StatelessWidget {
  final String value;
  final String label;
  const _MiniStat({required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value,
          style: GoogleFonts.jetBrainsMono(
            fontSize: 22, color: BFColors.cream,
            fontWeight: FontWeight.w500, letterSpacing: -0.6,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label.toUpperCase(),
          style: GoogleFonts.jetBrainsMono(
            fontSize: 9, color: BFColors.creamMute,
            fontWeight: FontWeight.w500, letterSpacing: 1.6,
          ),
        ),
      ],
    );
  }
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) {
    final items = [
      ('Progress', '04', '/progress', Icons.show_chart),
      ('Check-in', '05', '/checkin', Icons.check_circle_outline),
      ('Plan', '06', '/plan', Icons.calendar_today),
      ('Nutrition', '07', '/nutrition', Icons.restaurant_menu),
    ];
    return Column(
      children: items
          .map((a) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: RuledCard(
                  onTap: () => context.go(a.$3),
                  padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
                  child: Row(
                    children: [
                      Text(
                        a.$2,
                        style: GoogleFonts.fraunces(
                          fontSize: 22, color: BFColors.signal,
                          fontWeight: FontWeight.w300,
                          letterSpacing: -0.4,
                        ),
                      ),
                      const SizedBox(width: 18),
                      Text(
                        a.$1,
                        style: GoogleFonts.crimsonPro(
                          fontSize: 18, color: BFColors.cream,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const Spacer(),
                      Icon(a.$4, size: 18, color: BFColors.creamSoft),
                      const SizedBox(width: 14),
                      const Icon(Icons.arrow_forward, size: 14, color: BFColors.creamMute),
                    ],
                  ),
                ),
              ))
          .toList(),
    );
  }
}
