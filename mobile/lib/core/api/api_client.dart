import 'package:dio/dio.dart';
import '../storage/token_storage.dart';

class ApiClient {
  static const String _baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api/v1',
  );

  /// Bare client used for /auth/refresh — no interceptor, no recursion.
  static final Dio _refreshDio = Dio(BaseOptions(
    baseUrl: _baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
  ));

  static Future<bool> _tryRefresh() async {
    final refresh = await TokenStorage.getRefreshToken();
    if (refresh == null) return false;
    try {
      final resp = await _refreshDio.post('/auth/refresh', data: {'refresh_token': refresh});
      await TokenStorage.saveTokens(
        accessToken: resp.data['access_token'] as String,
        refreshToken: resp.data['refresh_token'] as String,
      );
      return true;
    } catch (_) {
      await TokenStorage.clear();
      return false;
    }
  }

  static Dio _build() {
    final dio = Dio(BaseOptions(
      baseUrl: _baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
    ));

    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final token = await TokenStorage.getAccessToken();
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        return handler.next(options);
      },
      onError: (e, handler) async {
        // Don't try to refresh on /auth/* endpoints (login, refresh themselves)
        final path = e.requestOptions.path;
        final isAuthCall = path.startsWith('/auth/');
        final alreadyRetried = e.requestOptions.extra['retried'] == true;

        if (e.response?.statusCode == 401 && !isAuthCall && !alreadyRetried) {
          final refreshed = await _tryRefresh();
          if (refreshed) {
            // Retry the original request with the new token
            final newToken = await TokenStorage.getAccessToken();
            final opts = e.requestOptions.copyWith();
            opts.headers['Authorization'] = 'Bearer $newToken';
            opts.extra['retried'] = true;
            try {
              final retry = await dio.fetch(opts);
              return handler.resolve(retry);
            } catch (retryErr) {
              return handler.next(retryErr is DioException ? retryErr : e);
            }
          }
        }

        if (e.response?.statusCode == 401) {
          await TokenStorage.clear();
        }
        return handler.next(e);
      },
    ));

    return dio;
  }

  static final Dio instance = _build();
}
