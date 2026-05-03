import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_theme.dart';
import 'editorial.dart';

/// Editorial empty/error/loading card.
/// Style: ruled border, oversized Fraunces title, Crimson Pro body, mono CTA.
class FriendlyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;
  final Color? iconColor;

  const FriendlyState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.actionLabel,
    this.onAction,
    this.iconColor,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(28),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 76, height: 76,
                decoration: BoxDecoration(
                  border: Border.all(color: iconColor ?? BFColors.signal, width: 1),
                ),
                alignment: Alignment.center,
                child: Icon(icon, size: 36, color: iconColor ?? BFColors.signal),
              ),
              const SizedBox(height: 24),
              Text(title, style: Theme.of(context).textTheme.displaySmall),
              const SizedBox(height: 14),
              Text(
                message,
                style: GoogleFonts.crimsonPro(
                  fontSize: 17, color: BFColors.creamSoft,
                  height: 1.5, fontStyle: FontStyle.italic,
                ),
              ),
              if (actionLabel != null && onAction != null) ...[
                const SizedBox(height: 28),
                EditorialPrimaryButton(
                  label: actionLabel!,
                  onPressed: onAction,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
