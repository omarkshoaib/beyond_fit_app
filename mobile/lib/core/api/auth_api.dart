import 'api_client.dart';
import '../models/models.dart';
import '../storage/token_storage.dart';

class AuthApi {
  static final _dio = ApiClient.instance;

  static Future<void> register({
    required String email,
    required String password,
    required String name,
  }) async {
    final resp = await _dio.post('/auth/register', data: {
      'email': email,
      'password': password,
      'name': name,
    });
    await TokenStorage.saveTokens(
      accessToken: resp.data['access_token'] as String,
      refreshToken: resp.data['refresh_token'] as String,
    );
  }

  static Future<void> login({
    required String email,
    required String password,
  }) async {
    final resp = await _dio.post('/auth/login', data: {
      'email': email,
      'password': password,
    });
    await TokenStorage.saveTokens(
      accessToken: resp.data['access_token'] as String,
      refreshToken: resp.data['refresh_token'] as String,
    );
  }

  static Future<UserProfile> me() async {
    final resp = await _dio.get('/auth/me');
    return UserProfile.fromJson(resp.data as Map<String, dynamic>);
  }

  static Future<void> logout() => TokenStorage.clear();

  static Future<void> forgotPassword({required String email}) async {
    await _dio.post('/auth/forgot', data: {'email': email});
  }

  static Future<void> resetPassword({required String token, required String newPassword}) async {
    final resp = await _dio.post('/auth/reset', data: {
      'token': token,
      'new_password': newPassword,
    });
    await TokenStorage.saveTokens(
      accessToken: resp.data['access_token'] as String,
      refreshToken: resp.data['refresh_token'] as String,
    );
  }

  static Future<void> verifyEmail(String token) async {
    await _dio.post('/auth/verify', data: {'token': token});
  }

  static Future<void> resendVerification() async {
    await _dio.post('/auth/resend-verification');
  }
}
