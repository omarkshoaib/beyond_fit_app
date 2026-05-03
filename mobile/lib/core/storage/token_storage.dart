import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Token storage that adapts to platform:
/// - Native (iOS/Android): Keychain / EncryptedSharedPreferences via flutter_secure_storage
/// - Web: localStorage via shared_preferences (NOT secure; dev/MVP only)
class TokenStorage {
  static const _accessKey = 'access_token';
  static const _refreshKey = 'refresh_token';
  static const _secure = FlutterSecureStorage();

  static Future<void> saveAccessToken(String accessToken) async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      await p.setString(_accessKey, accessToken);
    } else {
      await _secure.write(key: _accessKey, value: accessToken);
    }
  }

  static Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      await p.setString(_accessKey, accessToken);
      await p.setString(_refreshKey, refreshToken);
    } else {
      await Future.wait([
        _secure.write(key: _accessKey, value: accessToken),
        _secure.write(key: _refreshKey, value: refreshToken),
      ]);
    }
  }

  static Future<String?> getAccessToken() async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      return p.getString(_accessKey);
    }
    return _secure.read(key: _accessKey);
  }

  static Future<String?> getRefreshToken() async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      return p.getString(_refreshKey);
    }
    return _secure.read(key: _refreshKey);
  }

  static Future<void> clear() async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      await Future.wait([p.remove(_accessKey), p.remove(_refreshKey)]);
    } else {
      await Future.wait([
        _secure.delete(key: _accessKey),
        _secure.delete(key: _refreshKey),
      ]);
    }
  }
}
