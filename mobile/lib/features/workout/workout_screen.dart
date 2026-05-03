import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/plans_api.dart';
import '../../core/api/sets_api.dart';
import '../../core/models/models.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/units.dart';
import '../../core/widgets/editorial.dart';

class WorkoutScreen extends StatefulWidget {
  const WorkoutScreen({super.key});

  @override
  State<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends State<WorkoutScreen> {
  TodaySession? _session;
  WorkoutPlan? _plan;
  bool _loading = true;
  final Set<String> _loggedSets = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await PlansApi.getToday();
      WorkoutPlan? p;
      try {
        p = await PlansApi.getCurrent();
      } catch (_) {/* no current plan */}
      if (mounted) setState(() {
        _session = s;
        _plan = p;
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _markLogged(int slotIdx, int setIdx) {
    setState(() => _loggedSets.add('$slotIdx-$setIdx'));
  }

  bool _isLogged(int slotIdx, int setIdx) => _loggedSets.contains('$slotIdx-$setIdx');

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
                : _session == null || _session!.isRestDay
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.hotel, size: 48, color: BFColors.creamSoft),
                            const SizedBox(height: 14),
                            Text('Rest Day', style: Theme.of(context).textTheme.displaySmall),
                          ],
                        ),
                      )
                    : _buildList(),
          ),
        ],
      ),
    );
  }

  Widget _buildList() {
    return CustomScrollView(
      slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
            child: Row(
              children: [
                IconButton(
                  icon: const Icon(Icons.arrow_back),
                  onPressed: () => Navigator.of(context).pop(),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
                const SizedBox(width: 8),
                Text(
                  'DAY ${_session!.dayIndex + 1} OF ${_session!.totalDays}',
                  style: GoogleFonts.jetBrainsMono(
                    fontSize: 10, color: BFColors.creamMute,
                    fontWeight: FontWeight.w500, letterSpacing: 1.8,
                  ),
                ),
              ],
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
            child: Text(
              _session!.dayName,
              style: GoogleFonts.fraunces(
                fontSize: 56, height: 0.92, color: BFColors.cream,
                fontWeight: FontWeight.w500,
                letterSpacing: -1.8,
              ),
            ),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
            child: Row(
              children: [
                Container(width: 28, height: 1, color: BFColors.inkRule),
                const SizedBox(width: 10),
                Text(
                  '${_session!.slots.length} EXERCISES · LOG EACH SET BELOW',
                  style: GoogleFonts.jetBrainsMono(
                    fontSize: 9, color: BFColors.creamMute,
                    fontWeight: FontWeight.w500, letterSpacing: 1.6,
                  ),
                ),
              ],
            ),
          ),
        ),
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          sliver: SliverList.separated(
            itemCount: _session!.slots.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (ctx, i) {
              final slot = _session!.slots[i] as Map<String, dynamic>;
              return _SlotCard(
                slot: slot,
                index: i,
                historyId: _plan?.id ?? 0,
                dayIndex: _session!.dayIndex,
                isLogged: (setIdx) => _isLogged(i, setIdx),
                onLogged: (setIdx) => _markLogged(i, setIdx),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _SlotCard extends StatelessWidget {
  final Map<String, dynamic> slot;
  final int index;
  final int historyId;
  final int dayIndex;
  final bool Function(int setIdx) isLogged;
  final void Function(int setIdx) onLogged;

  const _SlotCard({
    required this.slot,
    required this.index,
    required this.historyId,
    required this.dayIndex,
    required this.isLogged,
    required this.onLogged,
  });

  @override
  Widget build(BuildContext context) {
    // WorkoutSlot serializes flat: exercise_name, exercise_id, sets, reps, rpe,
    // target_weight, slot_type, coaching_cues, biomechanical_focus, rest_seconds.
    final name = (slot['exercise_name'] as String?) ?? 'Exercise ${index + 1}';
    final sets = _asInt(slot['sets']);
    final reps = slot['reps']?.toString() ?? '0';
    final weight = slot['target_weight'] as num?;
    final rpe = slot['rpe'];
    final slotType = slot['slot_type'] as String? ?? '';
    final restSec = slot['rest_seconds'] as int?;
    final cues = (slot['coaching_cues'] as List?)?.cast<String>() ?? const [];

    return RuledCard(
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: position number + slot-type badge + RPE
          Row(
            children: [
              Text(
                '${(index + 1).toString().padLeft(2, '0')}.',
                style: GoogleFonts.fraunces(
                  fontSize: 22, color: BFColors.signal,
                  fontWeight: FontWeight.w400,
                  fontStyle: FontStyle.italic,
                  letterSpacing: -0.4,
                ),
              ),
              const SizedBox(width: 8),
              _SlotBadge(slotType: slotType),
              const Spacer(),
              if (rpe != null)
                Text('RPE $rpe',
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 11, color: BFColors.creamMute,
                      fontWeight: FontWeight.w500, letterSpacing: 1.4,
                    )),
            ],
          ),
          const SizedBox(height: 8),
          // Exercise name in Fraunces
          Text(
            name,
            style: GoogleFonts.fraunces(
              fontSize: 22, height: 1.05, color: BFColors.cream,
              fontWeight: FontWeight.w600,
              letterSpacing: -0.4,
            ),
          ),
          const SizedBox(height: 12),
          // Stat row
          Row(
            children: [
              _StatChip(label: '$sets×$reps', icon: Icons.repeat),
              const SizedBox(width: 8),
              if (weight != null)
                _StatChip(label: Units.format(weight), icon: Icons.monitor_weight_outlined),
              if (restSec != null) ...[
                const SizedBox(width: 8),
                _StatChip(label: '${restSec}s rest', icon: Icons.schedule),
              ],
            ],
          ),
          // Coaching cues — show first cue inline if present
          if (cues.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              decoration: BoxDecoration(
                color: BFColors.signal.withValues(alpha: 0.07),
                border: Border(left: BorderSide(color: BFColors.signal.withValues(alpha: 0.5), width: 2)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.lightbulb_outline, size: 14, color: BFColors.signal),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      cues.first,
                      style: GoogleFonts.crimsonPro(
                        fontSize: 14, fontStyle: FontStyle.italic,
                        color: BFColors.creamSoft, height: 1.3,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 14),
          const RuledLine(),
          const SizedBox(height: 12),
          // Per-set log chips
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: List.generate(sets, (setIdx) {
              final logged = isLogged(setIdx);
              return _SetLogChip(
                setIndex: setIdx,
                logged: logged,
                onTap: logged ? null : () => _showLogSheet(context, setIdx),
              );
            }),
          ),
        ],
      ),
    );
  }

  static int _asInt(dynamic v) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    if (v is String) return int.tryParse(v) ?? 3;
    return 3;
  }

  Future<void> _showLogSheet(BuildContext context, int setIdx) async {
    final repsCtrl = TextEditingController(text: '${slot['reps']}');
    final weightCtrl = TextEditingController(
        text: slot['target_weight'] != null
            ? Units.fromKg((slot['target_weight'] as num).toDouble()).toString()
            : '');
    final rpeCtrl = TextEditingController(text: '${slot['rpe'] ?? ''}');

    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: BFColors.ink,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
      builder: (ctx) => _LogSheet(
        setIdx: setIdx,
        repsCtrl: repsCtrl, weightCtrl: weightCtrl, rpeCtrl: rpeCtrl,
        onSave: (reps, weightKg, rpe) async {
          await SetsApi.log(
            historyId: historyId,
            dayIndex: dayIndex,
            slotIndex: index,
            setIndex: setIdx,
            actualReps: reps,
            actualWeight: weightKg,
            rpe: rpe,
          );
        },
      ),
    );
    if (ok == true) onLogged(setIdx);
  }
}

class _LogSheet extends StatefulWidget {
  final int setIdx;
  final TextEditingController repsCtrl;
  final TextEditingController weightCtrl;
  final TextEditingController rpeCtrl;
  final Future<void> Function(int reps, double weightKg, int? rpe) onSave;

  const _LogSheet({
    required this.setIdx, required this.repsCtrl,
    required this.weightCtrl, required this.rpeCtrl,
    required this.onSave,
  });

  @override
  State<_LogSheet> createState() => _LogSheetState();
}

class _LogSheetState extends State<_LogSheet> {
  bool _saving = false;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 24, right: 24, top: 24,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionLabel(number: '${widget.setIdx + 1}', label: 'Log set'),
          const SizedBox(height: 12),
          Text('Set ${widget.setIdx + 1}', style: Theme.of(context).textTheme.displaySmall),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: widget.repsCtrl,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
                  decoration: const InputDecoration(labelText: 'REPS'),
                  autofocus: true,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: widget.weightCtrl,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
                  decoration: InputDecoration(labelText: 'WEIGHT (${Units.current.toUpperCase()})'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: widget.rpeCtrl,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
            decoration: const InputDecoration(labelText: 'RPE (1-10) · OPTIONAL'),
          ),
          const SizedBox(height: 20),
          EditorialPrimaryButton(
            label: 'Save set',
            busy: _saving,
            onPressed: _saving ? null : () async {
              final reps = int.tryParse(widget.repsCtrl.text.trim());
              final weightInput = double.tryParse(widget.weightCtrl.text.trim());
              final rpe = int.tryParse(widget.rpeCtrl.text.trim());
              if (reps == null || reps <= 0 || weightInput == null || weightInput < 0) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Enter valid reps and weight')));
                return;
              }
              setState(() => _saving = true);
              try {
                await widget.onSave(reps, Units.toKg(weightInput), rpe);
                if (mounted) Navigator.pop(context, true);
              } catch (_) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Could not save (offline?)')));
                  setState(() => _saving = false);
                }
              }
            },
          ),
        ],
      ),
    );
  }
}

class _SetLogChip extends StatelessWidget {
  final int setIndex;
  final bool logged;
  final VoidCallback? onTap;
  const _SetLogChip({required this.setIndex, required this.logged, this.onTap});

  @override
  Widget build(BuildContext context) {
    final color = logged ? BFColors.success : BFColors.signal;
    return InkWell(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          border: Border.all(color: color.withValues(alpha: 0.55)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(logged ? Icons.check : Icons.add, size: 14, color: color),
            const SizedBox(width: 8),
            Text(
              'SET ${setIndex + 1}',
              style: GoogleFonts.jetBrainsMono(
                fontSize: 11, color: color,
                fontWeight: FontWeight.w600, letterSpacing: 1.6,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SlotBadge extends StatelessWidget {
  final String slotType;
  const _SlotBadge({required this.slotType});

  @override
  Widget build(BuildContext context) {
    final label = switch (slotType) {
      'main_compound' => 'MAIN',
      'secondary_compound' => 'SEC',
      'isolation' => 'ISO',
      _ => slotType.toUpperCase(),
    };
    final color = switch (slotType) {
      'main_compound' => BFColors.signal,
      'secondary_compound' => BFColors.signalSoft,
      _ => BFColors.creamMute,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: 0.6), width: 1)),
      child: Text(label,
          style: GoogleFonts.jetBrainsMono(
            fontSize: 9, color: color,
            fontWeight: FontWeight.w600, letterSpacing: 1.6,
          )),
    );
  }
}

class _StatChip extends StatelessWidget {
  final String label;
  final IconData icon;
  const _StatChip({required this.label, required this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(border: Border.all(color: BFColors.inkRule)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: BFColors.creamMute),
          const SizedBox(width: 6),
          Text(label,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 12, color: BFColors.cream,
                fontWeight: FontWeight.w500, letterSpacing: 0.4,
              )),
        ],
      ),
    );
  }
}
