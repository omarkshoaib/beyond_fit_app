import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

/// Beyond Fit's design language: "Midnight Olympic Manual".
/// Deep ink paper + warm cream type + signal-red accent.
/// Fraunces (serif display, variable opsz/wght), Crimson Pro (body),
/// JetBrains Mono (numerals + technical labels).
class BFColors {
  static const ink = Color(0xFF0E0D0B); // near-black paper
  static const inkSoft = Color(0xFF1A1815);
  static const inkRule = Color(0xFF2B2722);
  static const cream = Color(0xFFEDE5D4); // warm paper
  static const creamSoft = Color(0xFFC9C0AC);
  static const creamMute = Color(0xFF8E8773);
  static const signal = Color(0xFFD14B3D); // hot red accent
  static const signalSoft = Color(0xFFE8806F);
  static const success = Color(0xFF8FB066); // muted olive (matches palette)
}

class BFType {
  static TextTheme of(ColorScheme cs) {
    final ink = cs.onSurface;
    return TextTheme(
      // Editorial display — Fraunces, used for hero numbers, page titles
      displayLarge: GoogleFonts.fraunces(
        fontSize: 64, height: 0.92, color: ink,
        fontWeight: FontWeight.w400,
        letterSpacing: -2.4,
      ),
      displayMedium: GoogleFonts.fraunces(
        fontSize: 44, height: 0.95, color: ink,
        fontWeight: FontWeight.w400,
        letterSpacing: -1.4,
      ),
      displaySmall: GoogleFonts.fraunces(
        fontSize: 32, height: 1.0, color: ink,
        fontWeight: FontWeight.w500,
        letterSpacing: -0.8,
      ),

      // Headlines — Fraunces, page section titles
      headlineLarge: GoogleFonts.fraunces(
        fontSize: 28, height: 1.05, color: ink,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.4,
      ),
      headlineMedium: GoogleFonts.fraunces(
        fontSize: 22, height: 1.15, color: ink,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
      ),
      headlineSmall: GoogleFonts.fraunces(
        fontSize: 18, height: 1.2, color: ink,
        fontWeight: FontWeight.w600,
      ),

      // Titles — Crimson Pro semibold for card titles
      titleLarge: GoogleFonts.crimsonPro(
        fontSize: 20, height: 1.25, color: ink,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.1,
      ),
      titleMedium: GoogleFonts.crimsonPro(
        fontSize: 17, height: 1.3, color: ink,
        fontWeight: FontWeight.w600,
      ),
      titleSmall: GoogleFonts.crimsonPro(
        fontSize: 15, height: 1.35, color: ink,
        fontWeight: FontWeight.w600,
      ),

      // Body — Crimson Pro
      bodyLarge: GoogleFonts.crimsonPro(
        fontSize: 17, height: 1.5, color: ink,
        fontWeight: FontWeight.w400,
      ),
      bodyMedium: GoogleFonts.crimsonPro(
        fontSize: 15, height: 1.5, color: ink,
        fontWeight: FontWeight.w400,
      ),
      bodySmall: GoogleFonts.crimsonPro(
        fontSize: 13, height: 1.45, color: ink.withValues(alpha: 0.75),
        fontWeight: FontWeight.w400,
      ),

      // Labels — JetBrains Mono, uppercase, technical
      labelLarge: GoogleFonts.jetBrainsMono(
        fontSize: 12, height: 1.2, color: ink,
        fontWeight: FontWeight.w500,
        letterSpacing: 1.6,
      ),
      labelMedium: GoogleFonts.jetBrainsMono(
        fontSize: 11, height: 1.2, color: ink,
        fontWeight: FontWeight.w500,
        letterSpacing: 1.4,
      ),
      labelSmall: GoogleFonts.jetBrainsMono(
        fontSize: 10, height: 1.2, color: ink.withValues(alpha: 0.7),
        fontWeight: FontWeight.w500,
        letterSpacing: 1.6,
      ),
    );
  }

  /// Mono — for numerals (RPE values, weights, set counts)
  static TextStyle mono({
    required double size,
    Color? color,
    FontWeight weight = FontWeight.w500,
    double letterSpacing = 0,
  }) =>
      GoogleFonts.jetBrainsMono(
        fontSize: size,
        color: color,
        fontWeight: weight,
        letterSpacing: letterSpacing,
      );

  /// Italic Fraunces — for the "&" and emphasised words
  static TextStyle ital({
    required double size,
    Color? color,
    FontWeight weight = FontWeight.w400,
  }) =>
      GoogleFonts.fraunces(
        fontSize: size,
        color: color,
        fontWeight: weight,
        fontStyle: FontStyle.italic,
      );
}

class AppTheme {
  static ThemeData dark() {
    const cs = ColorScheme.dark(
      brightness: Brightness.dark,
      primary: BFColors.signal,
      onPrimary: BFColors.cream,
      secondary: BFColors.signalSoft,
      onSecondary: BFColors.ink,
      surface: BFColors.ink,
      surfaceContainerHighest: BFColors.inkSoft,
      onSurface: BFColors.cream,
      onSurfaceVariant: BFColors.creamSoft,
      outline: BFColors.inkRule,
      outlineVariant: BFColors.inkRule,
      error: BFColors.signal,
      onError: BFColors.cream,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: cs,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: BFColors.ink,
      textTheme: BFType.of(cs),
      // Status bar matches paper
      appBarTheme: AppBarTheme(
        backgroundColor: BFColors.ink,
        foregroundColor: BFColors.cream,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        systemOverlayStyle: const SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarBrightness: Brightness.dark,
          statusBarIconBrightness: Brightness.light,
        ),
        titleTextStyle: GoogleFonts.fraunces(
          fontSize: 22, color: BFColors.cream,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
        ),
      ),
      // Cards use hairline rules instead of elevation
      cardTheme: CardThemeData(
        color: BFColors.inkSoft,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(2),
          side: const BorderSide(color: BFColors.inkRule, width: 1),
        ),
      ),
      // Inputs: cream-soft baseline, no fill — just the underline
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: BFColors.inkSoft,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
        border: const OutlineInputBorder(
          borderSide: BorderSide(color: BFColors.inkRule),
          borderRadius: BorderRadius.zero,
        ),
        enabledBorder: const OutlineInputBorder(
          borderSide: BorderSide(color: BFColors.inkRule),
          borderRadius: BorderRadius.zero,
        ),
        focusedBorder: const OutlineInputBorder(
          borderSide: BorderSide(color: BFColors.signal, width: 1.4),
          borderRadius: BorderRadius.zero,
        ),
        labelStyle: GoogleFonts.jetBrainsMono(
          fontSize: 11, color: BFColors.creamMute,
          fontWeight: FontWeight.w500, letterSpacing: 1.6,
        ),
        floatingLabelStyle: GoogleFonts.jetBrainsMono(
          fontSize: 11, color: BFColors.signal,
          fontWeight: FontWeight.w500, letterSpacing: 1.6,
        ),
        prefixIconColor: BFColors.creamSoft,
        suffixIconColor: BFColors.creamSoft,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith(
              (s) => s.contains(WidgetState.disabled) ? BFColors.inkRule : BFColors.signal),
          foregroundColor: WidgetStateProperty.all(BFColors.cream),
          shape: WidgetStateProperty.all(
            const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
          ),
          textStyle: WidgetStateProperty.all(
            GoogleFonts.jetBrainsMono(
              fontSize: 12, fontWeight: FontWeight.w600, letterSpacing: 2.2,
            ),
          ),
          padding: WidgetStateProperty.all(
            const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          ),
          minimumSize: WidgetStateProperty.all(const Size.fromHeight(56)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: ButtonStyle(
          foregroundColor: WidgetStateProperty.all(BFColors.cream),
          side: WidgetStateProperty.all(
            const BorderSide(color: BFColors.inkRule, width: 1),
          ),
          shape: WidgetStateProperty.all(
            const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
          ),
          textStyle: WidgetStateProperty.all(
            GoogleFonts.jetBrainsMono(
              fontSize: 12, fontWeight: FontWeight.w500, letterSpacing: 2.2,
            ),
          ),
          padding: WidgetStateProperty.all(
            const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          ),
          minimumSize: WidgetStateProperty.all(const Size.fromHeight(56)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: ButtonStyle(
          foregroundColor: WidgetStateProperty.all(BFColors.signal),
          textStyle: WidgetStateProperty.all(
            GoogleFonts.jetBrainsMono(
              fontSize: 11, fontWeight: FontWeight.w500, letterSpacing: 1.8,
            ),
          ),
          shape: WidgetStateProperty.all(
            const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
          ),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: BFColors.inkRule, thickness: 1, space: 1,
      ),
      iconTheme: const IconThemeData(color: BFColors.cream, size: 22),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: BFColors.signal,
        linearTrackColor: BFColors.inkRule,
        circularTrackColor: BFColors.inkRule,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: BFColors.inkSoft,
        side: const BorderSide(color: BFColors.inkRule),
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        labelStyle: GoogleFonts.jetBrainsMono(
          fontSize: 11, color: BFColors.cream,
          fontWeight: FontWeight.w500, letterSpacing: 1.4,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: BFColors.cream,
        contentTextStyle: GoogleFonts.crimsonPro(
          fontSize: 15, color: BFColors.ink, fontWeight: FontWeight.w500,
        ),
        actionTextColor: BFColors.signal,
        behavior: SnackBarBehavior.floating,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: BFColors.ink,
        surfaceTintColor: BFColors.ink,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.zero),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: BFColors.inkSoft,
        surfaceTintColor: BFColors.inkSoft,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.zero),
        titleTextStyle: GoogleFonts.fraunces(
          fontSize: 22, color: BFColors.cream,
          fontWeight: FontWeight.w600,
        ),
        contentTextStyle: GoogleFonts.crimsonPro(
          fontSize: 15, color: BFColors.cream, height: 1.5,
        ),
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: BFColors.cream,
        unselectedLabelColor: BFColors.creamMute,
        indicatorColor: BFColors.signal,
        indicator: const UnderlineTabIndicator(
          borderSide: BorderSide(color: BFColors.signal, width: 2),
          insets: EdgeInsets.zero,
        ),
        labelStyle: GoogleFonts.jetBrainsMono(
          fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 1.8,
        ),
        unselectedLabelStyle: GoogleFonts.jetBrainsMono(
          fontSize: 11, fontWeight: FontWeight.w400, letterSpacing: 1.8,
        ),
      ),
    );
  }
}
