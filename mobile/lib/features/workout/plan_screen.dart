import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/plans_api.dart';
import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/units.dart';
import '../../core/widgets/editorial.dart';

class PlanScreen extends StatefulWidget {
  const PlanScreen({super.key});

  @override
  State<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends State<PlanScreen> {
  WorkoutPlan? _plan;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await PlansApi.getCurrent();
      if (mounted) setState(() { _plan = p; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Full Plan')),
      body: Stack(
        children: [
          const PaperGrain(opacity: 0.04),
          _loading
              ? const Center(child: CircularProgressIndicator(strokeWidth: 1.4))
              : _plan == null
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(28),
                        child: Text(
                          'No active plan yet.',
                          style: GoogleFonts.crimsonPro(
                            fontSize: 18, fontStyle: FontStyle.italic,
                            color: BFColors.creamSoft,
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                      children: [
                        _PlanHeader(plan: _plan!),
                        const SizedBox(height: 20),
                        ..._plan!.days.asMap().entries.map((e) {
                          final i = e.key;
                          final d = e.value as Map<String, dynamic>;
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: _DayCard(day: d, index: i),
                          );
                        }),
                      ],
                    ),
        ],
      ),
    );
  }
}

class _PlanHeader extends StatelessWidget {
  final WorkoutPlan plan;
  const _PlanHeader({required this.plan});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionLabel(number: '01', label: 'Active plan'),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            NumeralStat(value: '${plan.weekNumber}', label: 'Week', size: 64),
            const SizedBox(width: 24),
            Container(width: 1, height: 56, color: BFColors.inkRule),
            const SizedBox(width: 24),
            NumeralStat(value: '${plan.blockNumber}', label: 'Block', size: 64),
            const SizedBox(width: 24),
            Container(width: 1, height: 56, color: BFColors.inkRule),
            const SizedBox(width: 24),
            NumeralStat(value: '${plan.days.length}', label: 'Days/wk', size: 64),
          ],
        ),
        const SizedBox(height: 20),
        const RuledLine(),
      ],
    );
  }
}

class _DayCard extends StatelessWidget {
  final Map<String, dynamic> day;
  final int index;
  const _DayCard({required this.day, required this.index});

  @override
  Widget build(BuildContext context) {
    final dayName = day['day_name'] as String? ?? 'Day';
    final slots = (day['slots'] as List?) ?? [];

    return RuledCard(
      padding: EdgeInsets.zero,
      child: Theme(
        data: Theme.of(context).copyWith(
          dividerColor: Colors.transparent,
          splashColor: Colors.transparent,
          highlightColor: Colors.transparent,
        ),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
          childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 16),
          title: Row(
            children: [
              Text(
                '${(index + 1).toString().padLeft(2, '0')}.',
                style: GoogleFonts.fraunces(
                  fontSize: 22, color: BFColors.signal,
                  fontStyle: FontStyle.italic, fontWeight: FontWeight.w400,
                ),
              ),
              const SizedBox(width: 10),
              Text(
                dayName,
                style: GoogleFonts.fraunces(
                  fontSize: 22, color: BFColors.cream,
                  fontWeight: FontWeight.w600, letterSpacing: -0.4,
                ),
              ),
            ],
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 4, left: 32),
            child: Text(
              '${slots.length} EXERCISES',
              style: GoogleFonts.jetBrainsMono(
                fontSize: 9, color: BFColors.creamMute,
                fontWeight: FontWeight.w500, letterSpacing: 1.8,
              ),
            ),
          ),
          iconColor: BFColors.creamSoft,
          collapsedIconColor: BFColors.creamSoft,
          children: [
            const RuledLine(),
            const SizedBox(height: 6),
            ...slots.map((s) {
              final slot = s as Map<String, dynamic>;
              final name = slot['exercise_name'] as String? ?? '?';
              final sets = slot['sets'];
              final reps = slot['reps']?.toString() ?? '?';
              final weight = slot['target_weight'];
              final rpe = slot['rpe'];
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(name,
                              style: GoogleFonts.crimsonPro(
                                fontSize: 16, color: BFColors.cream,
                                fontWeight: FontWeight.w500,
                              )),
                          const SizedBox(height: 2),
                          Text(
                            '$sets×$reps${weight != null ? " · ${Units.format(weight)}" : ""} · RPE $rpe',
                            style: GoogleFonts.jetBrainsMono(
                              fontSize: 11, color: BFColors.creamMute,
                              fontWeight: FontWeight.w500, letterSpacing: 1,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}
