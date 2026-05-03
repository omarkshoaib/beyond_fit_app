import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/auth_api.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/editorial.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _loading = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await AuthApi.login(email: _emailCtrl.text.trim(), password: _passCtrl.text);
      final me = await AuthApi.me();
      if (mounted) {
        context.go(me.isCoach ? '/coach' : '/home');
      }
    } catch (e) {
      setState(() => _error = 'Invalid email or password');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          const PaperGrain(opacity: 0.05),
          // Top signal stripe
          Positioned(top: 0, left: 0, right: 0, child: Container(height: 4, color: BFColors.signal)),

          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 32),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 460),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const SizedBox(height: 32),

                        // Brand mark
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              'beyond',
                              style: GoogleFonts.fraunces(
                                fontSize: 36, color: BFColors.cream,
                                fontWeight: FontWeight.w700,
                                letterSpacing: -1.2,
                              ),
                            ),
                            Text(
                              '&',
                              style: BFType.ital(
                                size: 36, color: BFColors.signal, weight: FontWeight.w400,
                              ),
                            ),
                            Text(
                              'fit',
                              style: GoogleFonts.fraunces(
                                fontSize: 36, color: BFColors.cream,
                                fontWeight: FontWeight.w700,
                                letterSpacing: -1.2,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'DETERMINISTIC · COACHING · ENGINE',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.jetBrainsMono(
                            fontSize: 9, color: BFColors.creamMute,
                            fontWeight: FontWeight.w500, letterSpacing: 3,
                          ),
                        ),

                        const SizedBox(height: 64),

                        SectionLabel(number: '01', label: 'Sign in'),
                        const SizedBox(height: 12),

                        Text(
                          'Welcome\nback.',
                          style: Theme.of(context).textTheme.displayMedium,
                        ),
                        const SizedBox(height: 32),

                        TextFormField(
                          controller: _emailCtrl,
                          keyboardType: TextInputType.emailAddress,
                          autofillHints: const [AutofillHints.email],
                          style: GoogleFonts.crimsonPro(
                            fontSize: 17, color: BFColors.cream,
                          ),
                          decoration: const InputDecoration(
                            labelText: 'EMAIL',
                            prefixIcon: Icon(Icons.alternate_email, size: 18),
                          ),
                          validator: (v) => (v == null || !v.contains('@')) ? 'Enter a valid email' : null,
                        ),
                        const SizedBox(height: 14),
                        TextFormField(
                          controller: _passCtrl,
                          obscureText: _obscure,
                          autofillHints: const [AutofillHints.password],
                          style: GoogleFonts.crimsonPro(
                            fontSize: 17, color: BFColors.cream,
                          ),
                          decoration: InputDecoration(
                            labelText: 'PASSWORD',
                            prefixIcon: const Icon(Icons.lock_outline, size: 18),
                            suffixIcon: IconButton(
                              icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility, size: 18),
                              onPressed: () => setState(() => _obscure = !_obscure),
                            ),
                          ),
                          validator: (v) => (v == null || v.length < 6) ? 'Min 6 characters' : null,
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 14),
                          Container(
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: BFColors.signal.withValues(alpha: 0.12),
                              border: Border.all(color: BFColors.signal.withValues(alpha: 0.45)),
                            ),
                            child: Row(
                              children: [
                                const Icon(Icons.error_outline, color: BFColors.signal, size: 18),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Text(
                                    _error!,
                                    style: GoogleFonts.jetBrainsMono(
                                      fontSize: 11, color: BFColors.signal,
                                      letterSpacing: 1.4,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 28),
                        EditorialPrimaryButton(
                          label: 'Sign in',
                          onPressed: _loading ? null : _submit,
                          busy: _loading,
                        ),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            TextButton(
                              onPressed: () => context.go('/forgot'),
                              child: const Text('FORGOT PASSWORD'),
                            ),
                            TextButton(
                              onPressed: () => context.go('/register'),
                              child: const Text('SIGN UP →'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
