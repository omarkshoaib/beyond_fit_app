import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';
import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  UserProfile? _profile;
  TodaySession? _today;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        AuthApi.me(),
        PlansApi.getToday(),
      ]);
      if (mounted) {
        setState(() {
          _profile = results[0] as UserProfile;
          _today = results[1] as TodaySession;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_profile != null ? 'Hey, ${_profile!.name ?? 'Athlete'}' : 'Beyond Fit'),
        actions: [
          IconButton(
            icon: const Icon(Icons.person_outline),
            onPressed: () => context.go('/profile'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _WeekBadge(weekNumber: _profile?.weekNumber ?? 1),
                      const SizedBox(height: 20),
                      _TodayCard(session: _today!),
                      const SizedBox(height: 16),
                      _QuickActions(),
                    ],
                  ),
                ),
    );
  }
}

class _WeekBadge extends StatelessWidget {
  final int weekNumber;
  const _WeekBadge({required this.weekNumber});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primary.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        'Week $weekNumber',
        style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600),
      ),
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
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              const Icon(Icons.hotel, size: 48, color: Colors.grey),
              const SizedBox(height: 12),
              Text('Rest Day', style: theme.textTheme.headlineSmall),
              const SizedBox(height: 4),
              const Text('Recovery is part of training.', style: TextStyle(color: Colors.grey)),
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
                  Text("Today's Session", style: theme.textTheme.labelLarge?.copyWith(color: Colors.grey)),
                  const Icon(Icons.arrow_forward_ios, size: 14, color: Colors.grey),
                ],
              ),
              const SizedBox(height: 8),
              Text(session.dayName, style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              Text('${session.slots.length} exercises', style: const TextStyle(color: Colors.grey)),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () => GoRouter.of(context).go('/workout'),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Start Workout'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _QuickActions extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final actions = [
      ('Progress', Icons.show_chart, '/progress'),
      ('Check-in', Icons.check_circle_outline, '/checkin'),
      ('Plan', Icons.calendar_today, '/plan'),
      ('Nutrition', Icons.restaurant_menu, '/nutrition'),
    ];

    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 12,
      mainAxisSpacing: 12,
      childAspectRatio: 2.2,
      children: actions
          .map((a) => Card(
                child: InkWell(
                  onTap: () => context.go(a.$3),
                  borderRadius: BorderRadius.circular(16),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Row(
                      children: [
                        Icon(a.$2, size: 22, color: Theme.of(context).colorScheme.primary),
                        const SizedBox(width: 10),
                        Text(a.$1, style: const TextStyle(fontWeight: FontWeight.w600)),
                      ],
                    ),
                  ),
                ),
              ))
          .toList(),
    );
  }
}
