import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/api/auth_api.dart';

class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  bool _loading = false;
  bool _sent = false;

  @override
  void dispose() {
    _emailCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _loading = true);
    try {
      await AuthApi.forgotPassword(email: _emailCtrl.text.trim());
      if (mounted) setState(() { _sent = true; _loading = false; });
    } catch (_) {
      // Backend always 200s; only network errors land here.
      if (mounted) setState(() { _sent = true; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        elevation: 0,
        leading: BackButton(onPressed: () => context.go('/login')),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: _sent
                  ? Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.mark_email_read_outlined,
                            size: 64, color: theme.colorScheme.primary),
                        const SizedBox(height: 24),
                        Text('Check your inbox',
                            style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
                        const SizedBox(height: 12),
                        Text(
                          'If that email is registered, a reset link is on the way. The link expires in 30 minutes.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Colors.grey.shade400),
                        ),
                        const SizedBox(height: 32),
                        FilledButton(
                          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(54)),
                          onPressed: () => context.go('/login'),
                          child: const Text('Back to sign in'),
                        ),
                      ],
                    )
                  : Form(
                      key: _formKey,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text('Reset password',
                              style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
                          const SizedBox(height: 8),
                          Text(
                            "Enter your email and we'll send you a reset link.",
                            style: TextStyle(color: Colors.grey.shade400),
                          ),
                          const SizedBox(height: 32),
                          TextFormField(
                            controller: _emailCtrl,
                            keyboardType: TextInputType.emailAddress,
                            decoration: const InputDecoration(
                              labelText: 'Email',
                              prefixIcon: Icon(Icons.mail_outline),
                            ),
                            validator: (v) => (v == null || !v.contains('@')) ? 'Enter a valid email' : null,
                          ),
                          const SizedBox(height: 24),
                          FilledButton(
                            style: FilledButton.styleFrom(
                              minimumSize: const Size.fromHeight(54),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                            ),
                            onPressed: _loading ? null : _submit,
                            child: _loading
                                ? const SizedBox(
                                    height: 22, width: 22,
                                    child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                                : const Text('Send reset link',
                                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                          ),
                        ],
                      ),
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
