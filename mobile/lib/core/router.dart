import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../features/auth/login_screen.dart';
import '../features/auth/register_screen.dart';
import '../features/home/home_screen.dart';
import '../features/workout/workout_screen.dart';
import '../features/workout/plan_screen.dart';
import '../features/workout/plan_history_screen.dart';
import '../features/checkin/checkin_screen.dart';
import '../features/progress/progress_screen.dart';
import '../features/profile/profile_screen.dart';
import '../features/profile/edit_profile_screen.dart';
import '../features/nutrition/nutrition_screen.dart';
import 'storage/token_storage.dart';

final router = GoRouter(
  initialLocation: '/login',
  redirect: (context, state) async {
    final token = await TokenStorage.getAccessToken();
    final onAuth = state.matchedLocation == '/login' || state.matchedLocation == '/register';
    if (token == null && !onAuth) return '/login';
    if (token != null && onAuth) return '/home';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
    GoRoute(path: '/register', builder: (context, state) => const RegisterScreen()),
    GoRoute(path: '/home', builder: (context, state) => const HomeScreen()),
    GoRoute(path: '/workout', builder: (context, state) => const WorkoutScreen()),
    GoRoute(path: '/plan', builder: (context, state) => const PlanScreen()),
    GoRoute(path: '/plan/history', builder: (context, state) => const PlanHistoryScreen()),
    GoRoute(path: '/checkin', builder: (context, state) => const CheckinScreen()),
    GoRoute(path: '/progress', builder: (context, state) => const ProgressScreen()),
    GoRoute(path: '/profile', builder: (context, state) => const ProfileScreen()),
    GoRoute(path: '/profile/edit', builder: (context, state) => const EditProfileScreen()),
    GoRoute(path: '/nutrition', builder: (context, state) => const NutritionScreen()),
  ],
  errorBuilder: (context, state) => Scaffold(
    body: Center(child: Text('Page not found: ${state.uri}')),
  ),
);
