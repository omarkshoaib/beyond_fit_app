import 'api_client.dart';
import '../models/models.dart';

class CoachApi {
  static final _dio = ApiClient.instance;

  static Future<List<CoachClient>> listClients() async {
    final resp = await _dio.get('/coach/clients');
    return (resp.data as List)
        .map((e) => CoachClient.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  static Future<List<PendingApproval>> listPending() async {
    final resp = await _dio.get('/coach/pending');
    return (resp.data as List)
        .map((e) => PendingApproval.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  static Future<PendingApproval> getPendingDetail(String approvalUuid) async {
    final resp = await _dio.get('/coach/pending/$approvalUuid');
    return PendingApproval.fromJson(resp.data as Map<String, dynamic>);
  }

  static Future<void> approve(String approvalUuid) async {
    await _dio.post('/coach/approve/$approvalUuid');
  }

  static Future<void> reject(String approvalUuid, String feedback) async {
    await _dio.post('/coach/reject/$approvalUuid', data: {'feedback': feedback});
  }
}

class AdminApi {
  static final _dio = ApiClient.instance;

  static Future<void> promoteCoach({required String email, bool isCoach = true, bool? isAdmin}) async {
    await _dio.post('/admin/promote', data: {
      'email': email,
      'is_coach': isCoach,
      if (isAdmin != null) 'is_admin': isAdmin,
    });
  }

  static Future<void> assignClientToCoach({required String clientEmail, required String coachEmail}) async {
    await _dio.post('/admin/assign', data: {
      'client_email': clientEmail,
      'coach_email': coachEmail,
    });
  }

  static Future<List<Map<String, dynamic>>> listClients() async {
    final resp = await _dio.get('/admin/clients');
    return (resp.data as List).cast<Map<String, dynamic>>();
  }

  static Future<List<Map<String, dynamic>>> listCoaches() async {
    final resp = await _dio.get('/admin/coaches');
    return (resp.data as List).cast<Map<String, dynamic>>();
  }

  static Future<List<Map<String, dynamic>>> listCoachInvites() async {
    final resp = await _dio.get('/admin/coaches/invites');
    return (resp.data as List).cast<Map<String, dynamic>>();
  }

  static Future<void> inviteCoach({required String email}) async {
    await _dio.post('/admin/coaches/invite', data: {'email': email});
  }

  static Future<void> withdrawCoachInvite({required String email}) async {
    await _dio.delete('/admin/coaches/invite/$email');
  }

  static Future<List<Map<String, dynamic>>> listAdmins() async {
    final resp = await _dio.get('/admin/admins');
    return (resp.data as List).cast<Map<String, dynamic>>();
  }

  static Future<void> promoteAdmin({required String email}) async {
    await _dio.post('/admin/admins/promote', data: {'email': email});
  }

  static Future<void> demoteAdmin({required String email}) async {
    await _dio.post('/admin/admins/demote', data: {'email': email});
  }
}
