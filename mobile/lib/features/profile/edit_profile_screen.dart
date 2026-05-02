import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/profile_api.dart';

class EditProfileScreen extends StatefulWidget {
  const EditProfileScreen({super.key});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  bool _loading = true;
  bool _saving = false;

  int _trainingDays = 3;
  String _experienceLevel = 'intermediate';
  List<String> _limitations = [];

  final _experienceLevels = ['beginner', 'intermediate', 'advanced'];
  final _availableLimitations = ['lower_back_pain', 'knee_pain', 'shoulder_pain'];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final p = await ProfileApi.getProfile();
      if (mounted) {
        setState(() {
          _trainingDays = p.trainingDays ?? 3;
          _experienceLevel = p.experienceLevel ?? 'intermediate';
          _limitations = List<String>.from(p.limitations ?? []);
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ProfileApi.updateProfile({
        'training_days': _trainingDays,
        'experience_level': _experienceLevel,
        'limitations': _limitations,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Profile updated')));
        context.go('/profile');
      }
    } catch (_) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Failed to save')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Edit Profile')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text('Training Days / Week', style: TextStyle(fontWeight: FontWeight.bold)),
                Slider(
                  value: _trainingDays.toDouble(),
                  min: 2,
                  max: 6,
                  divisions: 4,
                  label: '$_trainingDays days',
                  onChanged: (v) => setState(() => _trainingDays = v.round()),
                ),
                Center(child: Text('$_trainingDays days per week', style: const TextStyle(color: Colors.grey))),
                const SizedBox(height: 24),
                const Text('Experience Level', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: _experienceLevels
                      .map((lvl) => ChoiceChip(
                            label: Text(lvl.toUpperCase()),
                            selected: _experienceLevel == lvl,
                            onSelected: (_) => setState(() => _experienceLevel = lvl),
                          ))
                      .toList(),
                ),
                const SizedBox(height: 24),
                const Text('Limitations', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                const Text('Select any that apply', style: TextStyle(color: Colors.grey, fontSize: 13)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: _availableLimitations
                      .map((lim) => FilterChip(
                            label: Text(lim.replaceAll('_', ' ')),
                            selected: _limitations.contains(lim),
                            onSelected: (v) => setState(() {
                              if (v) {
                                _limitations.add(lim);
                              } else {
                                _limitations.remove(lim);
                              }
                            }),
                          ))
                      .toList(),
                ),
                const SizedBox(height: 32),
                ElevatedButton(
                  onPressed: _saving ? null : _save,
                  child: _saving
                      ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Save Changes'),
                ),
              ],
            ),
    );
  }
}
