import 'api_client.dart';
import '../models/models.dart';

class ProfileApi {
  static final _dio = ApiClient.instance;

  static Future<UserProfile> getProfile() async {
    final resp = await _dio.get('/profile');
    return UserProfile.fromJson(resp.data as Map<String, dynamic>);
  }

  static Future<void> updateProfile(Map<String, dynamic> updates) async {
    await _dio.put('/profile', data: updates);
  }

  static Future<ProgressData> getProgress() async {
    final resp = await _dio.get('/progress');
    return ProgressData.fromJson(resp.data as Map<String, dynamic>);
  }
}
