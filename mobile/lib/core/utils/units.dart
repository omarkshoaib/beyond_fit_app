import 'package:shared_preferences/shared_preferences.dart';

/// Weight unit preference. Default kg. Stored in shared_preferences (key: "weight_unit").
class Units {
  static const _key = 'weight_unit';
  static String _cached = 'kg';

  static Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    _cached = p.getString(_key) ?? 'kg';
  }

  static String get current => _cached;

  static bool get isLb => _cached == 'lb';

  static Future<void> setUnit(String unit) async {
    if (unit != 'kg' && unit != 'lb') return;
    _cached = unit;
    final p = await SharedPreferences.getInstance();
    await p.setString(_key, unit);
  }

  /// Convert kg → display value in current unit (rounded to 0.5).
  static double fromKg(double kg) {
    if (_cached == 'lb') return _round(kg * 2.20462);
    return _round(kg);
  }

  /// Convert display value back to kg for storage / API.
  static double toKg(double display) {
    if (_cached == 'lb') return _round(display / 2.20462);
    return _round(display);
  }

  static String format(num kg) {
    final v = fromKg(kg.toDouble());
    final str = v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);
    return '$str ${_cached}';
  }

  static double _round(double v) => (v * 2).roundToDouble() / 2;
}
