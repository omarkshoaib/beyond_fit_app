import 'api_client.dart';

class CheckinApi {
  static final _dio = ApiClient.instance;

  static Future<List<dynamic>> getHistory() async {
    final resp = await _dio.get('/checkin/history');
    return resp.data as List;
  }

  static Future<Map<String, dynamic>> submit({
    required int historyId,
    required List<Map<String, dynamic>> slots,
  }) async {
    final resp = await _dio.post('/checkin', data: {
      'history_id': historyId,
      'slots': slots,
    });
    return resp.data as Map<String, dynamic>;
  }
}
