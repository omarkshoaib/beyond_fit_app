import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../core/api/auth_api.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/editorial.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _loading = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _nameCtrl.dispose();
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
      await AuthApi.register(
        email: _emailCtrl.text.trim(),
        password: _passCtrl.text,
        name: _nameCtrl.text.trim(),
      );
      if (mounted) context.go('/onboarding');
    } catch (e) {
      setState(() => _error = 'Could not create account. Email may already be in use.');
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
          Positioned(top: 0, left: 0, right: 0, child: Container(height: 4, color: BFColors.signal)),
          SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 460),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: () => context.go('/login'),
                            icon: const Icon(Icons.arrow_back, size: 14),
                            label: const Text('BACK'),
                          ),
                        ),
                        const SizedBox(height: 32),
                        SectionLabel(number: '00', label: 'Create account'),
                        const SizedBox(height: 12),
                        Text('New\nathlete.',
                            style: Theme.of(context).textTheme.displayMedium),
                        const SizedBox(height: 8),
                        Text(
                          "We'll set up your training profile next.",
                          style: GoogleFonts.crimsonPro(
                            fontSize: 16, fontStyle: FontStyle.italic,
                            color: BFColors.creamSoft,
                          ),
                        ),
                        const SizedBox(height: 32),
                        TextFormField(
                          controller: _nameCtrl,
                          style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
                          decoration: const InputDecoration(
                            labelText: 'FULL NAME',
                            prefixIcon: Icon(Icons.person_outline, size: 18),
                          ),
                          validator: (v) => (v == null || v.trim().isEmpty) ? 'Enter your name' : null,
                        ),
                        const SizedBox(height: 14),
                        TextFormField(
                          controller: _emailCtrl,
                          keyboardType: TextInputType.emailAddress,
                          style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
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
                          style: GoogleFonts.crimsonPro(fontSize: 17, color: BFColors.cream),
                          decoration: InputDecoration(
                            labelText: 'PASSWORD',
                            prefixIcon: const Icon(Icons.lock_outline, size: 18),
                            suffixIcon: IconButton(
                              icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility, size: 18),
                              onPressed: () => setState(() => _obscure = !_obscure),
                            ),
                          ),
                          validator: (v) => (v == null || v.length < 8) ? 'Min 8 characters' : null,
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
                          label: 'Create account',
                          onPressed: _loading ? null : _submit,
                          busy: _loading,
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
