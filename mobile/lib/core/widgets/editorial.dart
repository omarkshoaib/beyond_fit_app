import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_theme.dart';

/// Monospace section label with leading rule and § number.
/// e.g.  ───── §·01  TODAY'S SESSION
class SectionLabel extends StatelessWidget {
  final String number;
  final String label;
  final Color? color;
  final EdgeInsetsGeometry? padding;

  const SectionLabel({
    super.key,
    required this.number,
    required this.label,
    this.color,
    this.padding,
  });

  @override
  Widget build(BuildContext context) {
    final c = color ?? BFColors.creamMute;
    return Padding(
      padding: padding ?? EdgeInsets.zero,
      child: Row(
        children: [
          Container(width: 36, height: 1, color: c),
          const SizedBox(width: 10),
          Text(
            '§·$number',
            style: GoogleFonts.jetBrainsMono(
              fontSize: 10, color: BFColors.signal,
              fontWeight: FontWeight.w600, letterSpacing: 1.6,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              label.toUpperCase(),
              style: GoogleFonts.jetBrainsMono(
                fontSize: 10, color: c,
                fontWeight: FontWeight.w500, letterSpacing: 1.8,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

/// Card with a hairline border, no elevation, slightly insetted.
class RuledCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry margin;
  final VoidCallback? onTap;
  final Color? background;
  final Color? borderColor;

  const RuledCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.margin = EdgeInsets.zero,
    this.onTap,
    this.background,
    this.borderColor,
  });

  @override
  Widget build(BuildContext context) {
    final container = Container(
      decoration: BoxDecoration(
        color: background ?? BFColors.inkSoft,
        border: Border.all(color: borderColor ?? BFColors.inkRule, width: 1),
      ),
      padding: padding,
      child: child,
    );
    final wrapped = onTap != null
        ? Material(
            color: Colors.transparent,
            child: InkWell(onTap: onTap, child: container),
          )
        : container;
    return Padding(padding: margin, child: wrapped);
  }
}

/// Numerical display: oversized JetBrains Mono numerals with a tiny serial
/// label underneath.  Used for week numbers, set counts, etc.
class NumeralStat extends StatelessWidget {
  final String value;
  final String label;
  final Color? accentColor;
  final double size;

  const NumeralStat({
    super.key,
    required this.value,
    required this.label,
    this.accentColor,
    this.size = 56,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value,
          style: GoogleFonts.fraunces(
            fontSize: size, height: 0.9,
            color: accentColor ?? BFColors.cream,
            fontWeight: FontWeight.w400,
            letterSpacing: -1.2,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label.toUpperCase(),
          style: GoogleFonts.jetBrainsMono(
            fontSize: 9, color: BFColors.creamMute,
            fontWeight: FontWeight.w500, letterSpacing: 1.8,
          ),
        ),
      ],
    );
  }
}

/// Hairline horizontal rule with optional left-side label (mono).
class RuledLine extends StatelessWidget {
  final String? leadLabel;
  final Color? color;
  final double topPadding;
  final double bottomPadding;

  const RuledLine({
    super.key,
    this.leadLabel,
    this.color,
    this.topPadding = 0,
    this.bottomPadding = 0,
  });

  @override
  Widget build(BuildContext context) {
    final c = color ?? BFColors.inkRule;
    return Padding(
      padding: EdgeInsets.only(top: topPadding, bottom: bottomPadding),
      child: Row(
        children: [
          if (leadLabel != null) ...[
            Text(
              leadLabel!,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 9, color: BFColors.creamMute,
                fontWeight: FontWeight.w500, letterSpacing: 1.6,
              ),
            ),
            const SizedBox(width: 10),
          ],
          Expanded(child: Container(height: 1, color: c)),
        ],
      ),
    );
  }
}

/// Paper-grain backdrop. Subtle noise pattern via CustomPaint that brings
/// life to flat ink surfaces. Use as the body of a Stack.
class PaperGrain extends StatelessWidget {
  final double opacity;
  const PaperGrain({super.key, this.opacity = 0.04});

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: IgnorePointer(
        child: CustomPaint(
          painter: _GrainPainter(opacity: opacity),
        ),
      ),
    );
  }
}

class _GrainPainter extends CustomPainter {
  final double opacity;
  _GrainPainter({required this.opacity});

  @override
  void paint(Canvas canvas, Size size) {
    // Pseudo-noise: a stable LCG so the texture doesn't churn between repaints.
    final paint = Paint()..color = BFColors.cream.withValues(alpha: opacity);
    int seed = 0x5f3759df;
    final cell = 2.0;
    for (double y = 0; y < size.height; y += cell) {
      for (double x = 0; x < size.width; x += cell) {
        seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF;
        if ((seed & 0xFF) < 18) {
          canvas.drawRect(Rect.fromLTWH(x, y, cell, cell), paint);
        }
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GrainPainter old) => old.opacity != opacity;
}

/// Editorial primary button — black bg, cream type, signal-red on hover.
/// Subtle but present hover translation echoing the landing page CTA.
class EditorialPrimaryButton extends StatefulWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool busy;

  const EditorialPrimaryButton({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.busy = false,
  });

  @override
  State<EditorialPrimaryButton> createState() => _EditorialPrimaryButtonState();
}

class _EditorialPrimaryButtonState extends State<EditorialPrimaryButton> {
  bool _hover = false;
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final disabled = widget.onPressed == null || widget.busy;
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      cursor: disabled ? SystemMouseCursors.basic : SystemMouseCursors.click,
      child: GestureDetector(
        onTapDown: (_) => setState(() => _down = true),
        onTapCancel: () => setState(() => _down = false),
        onTapUp: (_) => setState(() => _down = false),
        onTap: disabled ? null : widget.onPressed,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOutCubic,
          height: 56,
          transform: Matrix4.translationValues(
            _hover && !disabled ? -2 : 0,
            _hover && !disabled ? -2 : 0,
            0,
          )..scale(_down ? 0.99 : 1.0),
          decoration: BoxDecoration(
            color: disabled ? BFColors.inkRule : (_hover ? BFColors.signal : BFColors.cream),
            border: Border.all(color: disabled ? BFColors.inkRule : BFColors.cream, width: 1),
            boxShadow: _hover && !disabled
                ? [const BoxShadow(color: BFColors.signal, offset: Offset(4, 4))]
                : null,
          ),
          child: Center(
            child: widget.busy
                ? const SizedBox(
                    height: 18, width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2, color: BFColors.ink),
                  )
                : Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (widget.icon != null) ...[
                        Icon(widget.icon, size: 18,
                            color: _hover ? BFColors.cream : BFColors.ink),
                        const SizedBox(width: 10),
                      ],
                      Text(
                        widget.label.toUpperCase(),
                        style: GoogleFonts.jetBrainsMono(
                          fontSize: 12,
                          color: _hover ? BFColors.cream : BFColors.ink,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 2.2,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}
