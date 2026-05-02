import 'package:flutter/material.dart';
import 'core/router.dart';
import 'core/theme/app_theme.dart';

void main() {
  runApp(const BeyondFitApp());
}

class BeyondFitApp extends StatelessWidget {
  const BeyondFitApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'Beyond Fit',
      theme: AppTheme.dark(),
      routerConfig: router,
      debugShowCheckedModeBanner: false,
    );
  }
}
