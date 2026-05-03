import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';

class VerifyEmailScreen extends StatefulWidget {
  final String token;
  const VerifyEmailScreen({super.key, required this.token});

  @override
  State<VerifyEmailScreen> createState() => _VerifyEmailScreenState();
}

class _VerifyEmailScreenState extends State<VerifyEmailScreen> {
  bool _loading = true;
  bool _ok = false;

  @override
  void initState() {
    super.initState();
    _verify();
  }

  Future<void> _verify() async {
    try {
      await AuthApi.verifyEmail(widget.token);
      if (mounted) setState(() { _ok = true; _loading = false; });
    } catch (_) {
      if (mounted) setState(() { _ok = false; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: _loading
                ? const Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(),
                      SizedBox(height: 16),
                      Text('Verifying your email…'),
                    ],
                  )
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        _ok ? Icons.verified_outlined : Icons.error_outline,
                        size: 88,
                        color: _ok ? Colors.green : theme.colorScheme.error,
                      ),
                      const SizedBox(height: 24),
                      Text(
                        _ok ? 'Email verified' : 'Link expired or invalid',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _ok
                            ? "You're all set. Tap Continue to head to the app."
                            : 'Sign in and tap "Resend verification email" from your profile.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.grey.shade400),
                      ),
                      const SizedBox(height: 32),
                      FilledButton(
                        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(54)),
                        onPressed: () => context.go(_ok ? '/home' : '/login'),
                        child: Text(_ok ? 'Continue' : 'Back to sign in'),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}
