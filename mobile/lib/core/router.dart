import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../features/auth/login_screen.dart';
import '../features/auth/register_screen.dart';
import '../features/auth/forgot_password_screen.dart';
import '../features/auth/reset_password_screen.dart';
import '../features/auth/verify_email_screen.dart';
import '../features/onboarding/onboarding_screen.dart';
import '../features/home/home_screen.dart';
import '../features/workout/workout_screen.dart';
import '../features/workout/plan_screen.dart';
import '../features/workout/plan_history_screen.dart';
import '../features/checkin/checkin_screen.dart';
import '../features/progress/progress_screen.dart';
import '../features/profile/profile_screen.dart';
import '../features/profile/edit_profile_screen.dart';
import '../features/nutrition/nutrition_screen.dart';
import '../features/coach/coach_home_screen.dart';
import '../features/coach/coach_review_screen.dart';
import '../features/admin/admin_screen.dart';
import 'storage/token_storage.dart';

CustomTransitionPage<T> _fade<T>(Widget child) => CustomTransitionPage<T>(
      child: child,
      transitionDuration: const Duration(milliseconds: 220),
      transitionsBuilder: (_, animation, __, child) =>
          FadeTransition(opacity: animation, child: child),
    );

final router = GoRouter(
  initialLocation: '/login',
  redirect: (context, state) async {
    final token = await TokenStorage.getAccessToken();
    final loc = state.matchedLocation;
    final isPublic = loc == '/login' ||
        loc == '/register' ||
        loc == '/forgot' ||
        loc == '/reset' ||
        loc == '/verify';

    if (token == null && !isPublic) return '/login';
    if (token != null && (loc == '/login' || loc == '/register')) return '/home';
    return null;
  },
  routes: [
    GoRoute(path: '/login', pageBuilder: (c, s) => _fade(const LoginScreen())),
    GoRoute(path: '/register', pageBuilder: (c, s) => _fade(const RegisterScreen())),
    GoRoute(path: '/forgot', pageBuilder: (c, s) => _fade(const ForgotPasswordScreen())),
    GoRoute(
      path: '/reset',
      pageBuilder: (c, s) {
        final token = s.uri.queryParameters['token'] ?? '';
        return _fade(ResetPasswordScreen(token: token));
      },
    ),
    GoRoute(
      path: '/verify',
      pageBuilder: (c, s) {
        final token = s.uri.queryParameters['token'] ?? '';
        return _fade(VerifyEmailScreen(token: token));
      },
    ),
    GoRoute(path: '/onboarding', pageBuilder: (c, s) => _fade(const OnboardingScreen())),
    GoRoute(path: '/home', pageBuilder: (c, s) => _fade(const HomeScreen())),
    GoRoute(path: '/workout', pageBuilder: (c, s) => _fade(const WorkoutScreen())),
    GoRoute(path: '/plan', pageBuilder: (c, s) => _fade(const PlanScreen())),
    GoRoute(path: '/plan/history', pageBuilder: (c, s) => _fade(const PlanHistoryScreen())),
    GoRoute(path: '/checkin', pageBuilder: (c, s) => _fade(const CheckinScreen())),
    GoRoute(path: '/progress', pageBuilder: (c, s) => _fade(const ProgressScreen())),
    GoRoute(path: '/profile', pageBuilder: (c, s) => _fade(const ProfileScreen())),
    GoRoute(path: '/profile/edit', pageBuilder: (c, s) => _fade(const EditProfileScreen())),
    GoRoute(path: '/nutrition', pageBuilder: (c, s) => _fade(const NutritionScreen())),
    GoRoute(path: '/coach', pageBuilder: (c, s) => _fade(const CoachHomeScreen())),
    GoRoute(
      path: '/coach/review/:uuid',
      pageBuilder: (c, s) => _fade(CoachReviewScreen(approvalUuid: s.pathParameters['uuid']!)),
    ),
    GoRoute(path: '/admin', pageBuilder: (c, s) => _fade(const AdminScreen())),
  ],
  errorBuilder: (context, state) => Scaffold(
    body: Center(child: Text('Page not found: ${state.uri}')),
  ),
);
