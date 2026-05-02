import 'api_client.dart';
import '../models/models.dart';

class PlansApi {
  static final _dio = ApiClient.instance;

  static Future<WorkoutPlan> getCurrent() async {
    final resp = await _dio.get('/plans/current');
    return WorkoutPlan.fromJson(resp.data as Map<String, dynamic>);
  }

  static Future<TodaySession> getToday() async {
    final resp = await _dio.get('/plans/today');
    return TodaySession.fromJson(resp.data as Map<String, dynamic>);
  }

  static Future<List<PlanHistoryItem>> getHistory() async {
    final resp = await _dio.get('/plans/history');
    return (resp.data as List)
        .map((e) => PlanHistoryItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
