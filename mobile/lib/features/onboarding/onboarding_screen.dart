import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/plans_api.dart';
import '../../core/api/profile_api.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _pageCtrl = PageController();
  int _step = 0;
  bool _submitting = false;
  String? _submitError;

  String _avatar = 'powerbuilder';
  int _trainingDays = 4;
  String _experienceLevel = 'intermediate';
  final Set<String> _limitations = {};

  static const _totalSteps = 4;

  @override
  void dispose() {
    _pageCtrl.dispose();
    super.dispose();
  }

  void _next() {
    if (_step < _totalSteps - 1) {
      setState(() => _step++);
      _pageCtrl.nextPage(duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic);
    } else {
      _submit();
    }
  }

  void _back() {
    if (_step > 0) {
      setState(() => _step--);
      _pageCtrl.previousPage(duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic);
    }
  }

  // Visible-on-step-> 0 back button is wired through the StepHeader.

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _submitError = null;
    });
    try {
      await ProfileApi.updateProfile({
        'avatar': _avatar,
        'training_days': _trainingDays,
        'experience_level': _experienceLevel,
        'limitations': _limitations.toList(),
        'available_equipment': ['full_gym'],
      });
      await PlansApi.generate();
      if (mounted) context.go('/home');
    } catch (e) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _submitError = 'Could not generate your plan. Please try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _StepHeader(currentStep: _step, totalSteps: _totalSteps, onBack: _step > 0 ? _back : null),
            Expanded(
              child: PageView(
                controller: _pageCtrl,
                physics: const NeverScrollableScrollPhysics(),
                children: [
                  _AvatarStep(
                    selected: _avatar,
                    onSelect: (v) => setState(() => _avatar = v),
                  ),
                  _DaysStep(
                    days: _trainingDays,
                    onChange: (v) => setState(() => _trainingDays = v),
                  ),
                  _ExperienceStep(
                    selected: _experienceLevel,
                    onSelect: (v) => setState(() => _experienceLevel = v),
                  ),
                  _LimitationsStep(
                    selected: _limitations,
                    onToggle: (v) => setState(() {
                      if (_limitations.contains(v)) {
                        _limitations.remove(v);
                      } else {
                        _limitations.add(v);
                      }
                    }),
                  ),
                ],
              ),
            ),
            if (_submitError != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
                child: Text(_submitError!,
                    style: TextStyle(color: theme.colorScheme.error, fontSize: 13),
                    textAlign: TextAlign.center),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(56),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  ),
                  onPressed: _submitting ? null : _next,
                  child: _submitting
                      ? const SizedBox(
                          height: 22,
                          width: 22,
                          child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white),
                        )
                      : Text(
                          _step == _totalSteps - 1 ? 'Generate My Plan' : 'Continue',
                          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                        ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StepHeader extends StatelessWidget {
  final int currentStep;
  final int totalSteps;
  final VoidCallback? onBack;

  const _StepHeader({required this.currentStep, required this.totalSteps, this.onBack});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 12, 24, 16),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: onBack,
            color: onBack == null ? Colors.transparent : null,
          ),
          Expanded(
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(totalSteps, (i) {
                final active = i <= currentStep;
                return AnimatedContainer(
                  duration: const Duration(milliseconds: 250),
                  margin: const EdgeInsets.symmetric(horizontal: 4),
                  height: 6,
                  width: active ? 28 : 12,
                  decoration: BoxDecoration(
                    color: active ? theme.colorScheme.primary : Colors.grey.withValues(alpha: 0.3),
                    borderRadius: BorderRadius.circular(3),
                  ),
                );
              }),
            ),
          ),
          const SizedBox(width: 48),
        ],
      ),
    );
  }
}

class _StepLayout extends StatelessWidget {
  final String title;
  final String subtitle;
  final Widget child;

  const _StepLayout({required this.title, required this.subtitle, required this.child});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(subtitle, style: TextStyle(color: Colors.grey.shade400, fontSize: 15)),
          const SizedBox(height: 28),
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _AvatarStep extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelect;

  const _AvatarStep({required this.selected, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    final options = [
      ('powerlifter', 'Powerlifter', 'Squat, bench, deadlift focused. Strength is king.', Icons.fitness_center),
      ('powerbuilder', 'Powerbuilder', 'Strength + size. Heavy compounds with hypertrophy work.', Icons.bolt),
      ('gen_pop', 'General Fitness', 'Balanced training for health, looks, and longevity.', Icons.favorite),
    ];

    return _StepLayout(
      title: "What's your goal?",
      subtitle: "Pick the training style that matches what you want.",
      child: ListView.separated(
        itemCount: options.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (ctx, i) {
          final o = options[i];
          final isSelected = selected == o.$1;
          return _SelectableCard(
            selected: isSelected,
            onTap: () => onSelect(o.$1),
            child: Row(
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: isSelected
                        ? Theme.of(ctx).colorScheme.primary
                        : Theme.of(ctx).colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(o.$4, color: isSelected ? Colors.white : Colors.grey, size: 28),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(o.$2, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                      const SizedBox(height: 4),
                      Text(o.$3, style: TextStyle(color: Colors.grey.shade400, fontSize: 13)),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _DaysStep extends StatelessWidget {
  final int days;
  final ValueChanged<int> onChange;

  const _DaysStep({required this.days, required this.onChange});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return _StepLayout(
      title: 'Training frequency',
      subtitle: 'How many days per week can you commit to training?',
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '$days',
              style: theme.textTheme.displayLarge?.copyWith(
                fontWeight: FontWeight.bold,
                color: theme.colorScheme.primary,
                fontSize: 96,
              ),
            ),
            Text('days per week', style: TextStyle(color: Colors.grey.shade400, fontSize: 16)),
            const SizedBox(height: 32),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(4, (i) {
                final v = i + 3;
                final selected = v == days;
                return GestureDetector(
                  onTap: () => onChange(v),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.symmetric(horizontal: 6),
                    width: 56,
                    height: 56,
                    decoration: BoxDecoration(
                      color: selected
                          ? theme.colorScheme.primary
                          : theme.colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: selected
                            ? theme.colorScheme.primary
                            : Colors.transparent,
                        width: 2,
                      ),
                    ),
                    child: Center(
                      child: Text(
                        '$v',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 18,
                          color: selected ? Colors.white : Colors.grey,
                        ),
                      ),
                    ),
                  ),
                );
              }),
            ),
          ],
        ),
      ),
    );
  }
}

class _ExperienceStep extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelect;

  const _ExperienceStep({required this.selected, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    final options = [
      ('beginner', 'Beginner', 'Less than 1 year of consistent training.'),
      ('intermediate', 'Intermediate', '1–3 years. Solid form on the main lifts.'),
      ('advanced', 'Advanced', '3+ years. You know your numbers and recovery.'),
    ];

    return _StepLayout(
      title: 'Experience level',
      subtitle: 'This calibrates your weekly volume and intensity.',
      child: ListView.separated(
        itemCount: options.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (ctx, i) {
          final o = options[i];
          final isSelected = selected == o.$1;
          return _SelectableCard(
            selected: isSelected,
            onTap: () => onSelect(o.$1),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(o.$2, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                const SizedBox(height: 4),
                Text(o.$3, style: TextStyle(color: Colors.grey.shade400, fontSize: 13)),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _LimitationsStep extends StatelessWidget {
  final Set<String> selected;
  final ValueChanged<String> onToggle;

  const _LimitationsStep({required this.selected, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    final options = [
      ('lower_back_pain', 'Lower back pain', Icons.airline_seat_flat),
      ('knee_pain', 'Knee pain', Icons.directions_run),
      ('shoulder_pain', 'Shoulder pain', Icons.accessibility_new),
    ];

    return _StepLayout(
      title: 'Any injuries?',
      subtitle: 'We swap risky exercises for safer alternatives. Skip if none apply.',
      child: ListView.separated(
        itemCount: options.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (ctx, i) {
          final o = options[i];
          final isSelected = selected.contains(o.$1);
          return _SelectableCard(
            selected: isSelected,
            onTap: () => onToggle(o.$1),
            child: Row(
              children: [
                Icon(o.$3, color: isSelected ? Theme.of(ctx).colorScheme.primary : Colors.grey, size: 24),
                const SizedBox(width: 16),
                Expanded(child: Text(o.$2, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15))),
                if (isSelected)
                  Icon(Icons.check_circle, color: Theme.of(ctx).colorScheme.primary, size: 22),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SelectableCard extends StatelessWidget {
  final bool selected;
  final VoidCallback onTap;
  final Widget child;

  const _SelectableCard({required this.selected, required this.onTap, required this.child});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: theme.colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: selected ? theme.colorScheme.primary : Colors.transparent,
              width: 2,
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}
