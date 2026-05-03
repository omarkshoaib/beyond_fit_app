class UserProfile {
  final String clientId;
  final String email;
  final String? name;
  final String? avatar;
  final String? experienceLevel;
  final int? trainingDays;
  final List<String>? limitations;
  final List<String>? availableEquipment;
  final int? weekNumber;
  final bool isCoach;
  final bool isAdmin;
  final String? coachId;
  final String? verifiedAt;

  const UserProfile({
    required this.clientId,
    required this.email,
    this.name,
    this.avatar,
    this.experienceLevel,
    this.trainingDays,
    this.limitations,
    this.availableEquipment,
    this.weekNumber,
    this.isCoach = false,
    this.isAdmin = false,
    this.coachId,
    this.verifiedAt,
  });

  bool get isVerified => verifiedAt != null;

  factory UserProfile.fromJson(Map<String, dynamic> j) => UserProfile(
        clientId: j['client_id'] as String,
        email: j['email'] as String,
        name: j['name'] as String?,
        avatar: j['avatar'] as String?,
        experienceLevel: j['experience_level'] as String?,
        trainingDays: j['training_days'] as int?,
        limitations: (j['limitations'] as List?)?.cast<String>(),
        availableEquipment: (j['available_equipment'] as List?)?.cast<String>(),
        weekNumber: j['week_number'] as int?,
        isCoach: j['is_coach'] as bool? ?? false,
        isAdmin: j['is_admin'] as bool? ?? false,
        coachId: j['coach_id'] as String?,
        verifiedAt: j['verified_at'] as String?,
      );
}

class CoachClient {
  final String clientId;
  final String? name;
  final String email;
  final String? avatar;
  final int? trainingDays;
  final String? experienceLevel;
  final int? weekNumber;
  final int pendingCount;

  const CoachClient({
    required this.clientId,
    required this.email,
    this.name,
    this.avatar,
    this.trainingDays,
    this.experienceLevel,
    this.weekNumber,
    this.pendingCount = 0,
  });

  factory CoachClient.fromJson(Map<String, dynamic> j) => CoachClient(
        clientId: j['client_id'] as String,
        name: j['name'] as String?,
        email: j['email'] as String,
        avatar: j['avatar'] as String?,
        trainingDays: j['training_days'] as int?,
        experienceLevel: j['experience_level'] as String?,
        weekNumber: j['week_number'] as int?,
        pendingCount: j['pending_count'] as int? ?? 0,
      );
}

class PendingApproval {
  final String approvalUuid;
  final String clientId;
  final String clientName;
  final String clientEmail;
  final String? createdAt;
  final String coachingMessage;
  final Map<String, dynamic> workout;

  const PendingApproval({
    required this.approvalUuid,
    required this.clientId,
    required this.clientName,
    required this.clientEmail,
    this.createdAt,
    required this.coachingMessage,
    required this.workout,
  });

  factory PendingApproval.fromJson(Map<String, dynamic> j) => PendingApproval(
        approvalUuid: j['approval_uuid'] as String,
        clientId: j['client_id'] as String,
        clientName: j['client_name'] as String? ?? 'Client',
        clientEmail: j['client_email'] as String? ?? '',
        createdAt: j['created_at'] as String?,
        coachingMessage: j['coaching_message'] as String? ?? '',
        workout: j['workout'] as Map<String, dynamic>,
      );

  List<dynamic> get days => (workout['days'] as List?) ?? [];
  int get weekNumber => workout['week_number'] as int? ?? 1;
}

class WorkoutPlan {
  final int id;
  final int weekNumber;
  final int blockNumber;
  final String status;
  final String? planStartedAt;
  final Map<String, dynamic> workout;

  const WorkoutPlan({
    required this.id,
    required this.weekNumber,
    required this.blockNumber,
    required this.status,
    this.planStartedAt,
    required this.workout,
  });

  factory WorkoutPlan.fromJson(Map<String, dynamic> j) => WorkoutPlan(
        id: j['id'] as int,
        weekNumber: j['week_number'] as int,
        blockNumber: j['block_number'] as int,
        status: j['status'] as String,
        planStartedAt: j['plan_started_at'] as String?,
        workout: j['workout'] as Map<String, dynamic>,
      );

  List<dynamic> get days => (workout['days'] as List?) ?? [];
}

class TodaySession {
  final Map<String, dynamic>? day;
  final int dayIndex;
  final int totalDays;
  final bool noPlan;
  final bool pendingReview;
  final String? rejectionFeedback;

  const TodaySession({
    this.day,
    required this.dayIndex,
    required this.totalDays,
    this.noPlan = false,
    this.pendingReview = false,
    this.rejectionFeedback,
  });

  factory TodaySession.fromJson(Map<String, dynamic> j) => TodaySession(
        day: j['day'] as Map<String, dynamic>?,
        dayIndex: j['day_index'] as int? ?? 0,
        totalDays: j['total_days'] as int? ?? 0,
        noPlan: j['no_plan'] as bool? ?? false,
        pendingReview: j['pending_review'] as bool? ?? false,
        rejectionFeedback: j['rejection_feedback'] as String?,
      );

  String get dayName => day?['day_name'] as String? ?? 'Rest Day';
  List<dynamic> get slots => (day?['slots'] as List?) ?? [];
  bool get isRestDay => day == null && !noPlan;
}

class PlanHistoryItem {
  final int id;
  final int weekNumber;
  final String status;
  final String? createdAt;

  const PlanHistoryItem({
    required this.id,
    required this.weekNumber,
    required this.status,
    this.createdAt,
  });

  factory PlanHistoryItem.fromJson(Map<String, dynamic> j) => PlanHistoryItem(
        id: j['id'] as int,
        weekNumber: j['week_number'] as int,
        status: j['status'] as String,
        createdAt: j['created_at'] as String?,
      );
}

class ProgressData {
  final List<double> rpeTrend;
  final List<double> weightTrend;

  const ProgressData({required this.rpeTrend, required this.weightTrend});

  factory ProgressData.fromJson(Map<String, dynamic> j) => ProgressData(
        rpeTrend: (j['rpe_trend'] as List).map((e) => (e as num).toDouble()).toList(),
        weightTrend: (j['weight_trend'] as List).map((e) => (e as num).toDouble()).toList(),
      );
}
