import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';
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
    } catch (e) {
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
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = _profile?.name?.split(' ').first ?? 'Athlete';

    return Scaffold(
      appBar: AppBar(
        toolbarHeight: 72,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _greeting(),
              style: TextStyle(fontSize: 13, color: Colors.grey.shade400, fontWeight: FontWeight.w400),
            ),
            Text(name, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: GestureDetector(
              onTap: () => context.go('/profile'),
              child: CircleAvatar(
                radius: 18,
                backgroundColor: theme.colorScheme.primary,
                child: Text(
                  name.substring(0, 1).toUpperCase(),
                  style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                ),
              ),
            ),
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) return const Center(child: CircularProgressIndicator());

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
        iconColor: Colors.orange,
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
        iconColor: Colors.amber,
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
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _WeekBadge(weekNumber: _profile?.weekNumber ?? 1),
          const SizedBox(height: 20),
          _TodayCard(session: _today!),
          const SizedBox(height: 16),
          const _QuickActions(),
        ],
      ),
    );
  }
}

class _WeekBadge extends StatelessWidget {
  final int weekNumber;
  const _WeekBadge({required this.weekNumber});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: BoxDecoration(
            color: theme.colorScheme.primary.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(20),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.calendar_today, size: 14, color: theme.colorScheme.primary),
              const SizedBox(width: 6),
              Text(
                'Week $weekNumber',
                style: TextStyle(
                  color: theme.colorScheme.primary,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _TodayCard extends StatelessWidget {
  final TodaySession session;
  const _TodayCard({required this.session});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (session.isRestDay) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            children: [
              Icon(Icons.hotel, size: 56, color: Colors.grey.shade500),
              const SizedBox(height: 16),
              Text('Rest Day', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              Text(
                'Recovery is part of training.',
                style: TextStyle(color: Colors.grey.shade400),
              ),
            ],
          ),
        ),
      );
    }

    return Card(
      child: InkWell(
        onTap: () => GoRouter.of(context).go('/workout'),
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    "TODAY'S SESSION",
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: Colors.grey.shade400,
                      letterSpacing: 1.2,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Icon(Icons.arrow_forward_ios, size: 14, color: Colors.grey.shade500),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                session.dayName,
                style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  _ChipInfo(icon: Icons.fitness_center, label: '${session.slots.length} exercises'),
                  const SizedBox(width: 8),
                  _ChipInfo(icon: Icons.schedule, label: '~60 min'),
                ],
              ),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(50),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: () => GoRouter.of(context).go('/workout'),
                  icon: const Icon(Icons.play_arrow_rounded, size: 24),
                  label: const Text('Start Workout', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ChipInfo extends StatelessWidget {
  final IconData icon;
  final String label;
  const _ChipInfo({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: Colors.grey.shade400),
          const SizedBox(width: 5),
          Text(label, style: TextStyle(fontSize: 12, color: Colors.grey.shade300)),
        ],
      ),
    );
  }
}

class _QuickActions extends StatelessWidget {
  const _QuickActions();

  @override
  Widget build(BuildContext context) {
    final actions = [
      ('Progress', Icons.show_chart, '/progress', Colors.orange),
      ('Check-in', Icons.check_circle_outline, '/checkin', Colors.green),
      ('Full Plan', Icons.calendar_today, '/plan', Colors.blue),
      ('Nutrition', Icons.restaurant_menu, '/nutrition', Colors.purple),
    ];

    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 12,
      mainAxisSpacing: 12,
      childAspectRatio: 2.2,
      children: actions.map((a) {
        return Card(
          child: InkWell(
            onTap: () => context.go(a.$3),
            borderRadius: BorderRadius.circular(16),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: a.$4.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Icon(a.$2, size: 19, color: a.$4),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      a.$1,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}
