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
  });

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
      );
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

  const TodaySession({this.day, required this.dayIndex, required this.totalDays});

  factory TodaySession.fromJson(Map<String, dynamic> j) => TodaySession(
        day: j['day'] as Map<String, dynamic>?,
        dayIndex: j['day_index'] as int,
        totalDays: j['total_days'] as int,
      );

  String get dayName => day?['day_name'] as String? ?? 'Rest Day';
  List<dynamic> get slots => (day?['slots'] as List?) ?? [];
  bool get isRestDay => day == null;
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
