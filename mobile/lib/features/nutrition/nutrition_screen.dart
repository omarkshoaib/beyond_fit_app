import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';
import '../../core/api/api_client.dart';

class NutritionScreen extends StatefulWidget {
  const NutritionScreen({super.key});

  @override
  State<NutritionScreen> createState() => _NutritionScreenState();
}

class _NutritionScreenState extends State<NutritionScreen> {
  Map<String, dynamic>? _plan;
  bool _loading = true;
  bool _unavailable = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final resp = await ApiClient.instance.get('/nutrition/plan');
      if (mounted) setState(() { _plan = resp.data as Map<String, dynamic>?; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _unavailable = true; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Nutrition')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _unavailable || _plan == null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: const [
                        Icon(Icons.restaurant_menu, size: 64, color: Colors.grey),
                        SizedBox(height: 16),
                        Text('Nutrition plan not available',
                            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                        SizedBox(height: 8),
                        Text(
                          'Your nutrition plan will appear here once the feature is enabled for your account.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Colors.grey),
                        ),
                      ],
                    ),
                  ),
                )
              : _NutritionPlanView(plan: _plan!),
    );
  }
}

class _NutritionPlanView extends StatelessWidget {
  final Map<String, dynamic> plan;
  const _NutritionPlanView({required this.plan});

  @override
  Widget build(BuildContext context) {
    final meals = (plan['meals'] as List?) ?? [];
    final totalCalories = plan['total_calories'] as int?;
    final protein = plan['total_protein_g'] as num?;
    final carbs = plan['total_carbs_g'] as num?;
    final fat = plan['total_fat_g'] as num?;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _MacroChip('Calories', '${totalCalories ?? "—"}', Colors.orange),
                _MacroChip('Protein', '${protein?.toStringAsFixed(0) ?? "—"}g', BFColors.signalSoft),
                _MacroChip('Carbs', '${carbs?.toStringAsFixed(0) ?? "—"}g', BFColors.success),
                _MacroChip('Fat', '${fat?.toStringAsFixed(0) ?? "—"}g', BFColors.signal),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        ...meals.map((m) {
          final meal = m as Map<String, dynamic>;
          final mealName = meal['meal_type'] as String? ?? 'Meal';
          final foods = (meal['foods'] as List?) ?? [];
          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            child: ExpansionTile(
              title: Text(mealName.toUpperCase(), style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
              subtitle: Text('${foods.length} items', style: const TextStyle(color: Colors.grey, fontSize: 12)),
              children: foods.map((f) {
                final food = f as Map<String, dynamic>;
                return ListTile(
                  dense: true,
                  title: Text(food['name'] as String? ?? '?'),
                  trailing: Text('${food['serving_g'] ?? "?"}g', style: const TextStyle(color: Colors.grey)),
                );
              }).toList(),
            ),
          );
        }),
      ],
    );
  }
}

class _MacroChip extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _MacroChip(this.label, this.value, this.color);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: color)),
        const SizedBox(height: 2),
        Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11)),
      ],
    );
  }
}
