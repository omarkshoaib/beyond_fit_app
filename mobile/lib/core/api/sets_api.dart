import 'api_client.dart';

class SetsApi {
  static final _dio = ApiClient.instance;

  static Future<int> log({
    required int historyId,
    required int dayIndex,
    required int slotIndex,
    required int setIndex,
    required int actualReps,
    required double actualWeight,
    int? rpe,
  }) async {
    final resp = await _dio.post('/sets', data: {
      'history_id': historyId,
      'day_index': dayIndex,
      'slot_index': slotIndex,
      'set_index': setIndex,
      'actual_reps': actualReps,
      'actual_weight': actualWeight,
      if (rpe != null) 'rpe': rpe,
    });
    return resp.data['id'] as int;
  }

  static Future<List<Map<String, dynamic>>> listForHistory(int historyId) async {
    final resp = await _dio.get('/sets/by-history/$historyId');
    return (resp.data as List).cast<Map<String, dynamic>>();
  }
}

class FeedbackApi {
  static final _dio = ApiClient.instance;

  static Future<void> submit({required String message, String? appVersion}) async {
    await _dio.post('/feedback', data: {
      'message': message,
      if (appVersion != null) 'app_version': appVersion,
    });
  }
}
