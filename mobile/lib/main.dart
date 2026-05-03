import 'dart:async';

import 'package:app_links/app_links.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'core/router.dart';
import 'core/theme/app_theme.dart';
import 'core/utils/units.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Units.load();
  runApp(const BeyondFitApp());
}

class BeyondFitApp extends StatefulWidget {
  const BeyondFitApp({super.key});

  @override
  State<BeyondFitApp> createState() => _BeyondFitAppState();
}

class _BeyondFitAppState extends State<BeyondFitApp> {
  StreamSubscription<Uri>? _linkSub;

  @override
  void initState() {
    super.initState();
    if (!kIsWeb) {
      _wireDeepLinks();
    }
  }

  @override
  void dispose() {
    _linkSub?.cancel();
    super.dispose();
  }

  Future<void> _wireDeepLinks() async {
    try {
      final appLinks = AppLinks();

      // Cold-start: app launched by tapping a link
      final initial = await appLinks.getInitialLink();
      if (initial != null) _handleUri(initial);

      // Warm-start: app already running, link tapped
      _linkSub = appLinks.uriLinkStream.listen(_handleUri);
    } catch (_) {
      // Plugin not available on the current platform — ignore
    }
  }

  void _handleUri(Uri uri) {
    // Map https://beyondfit.app/<path>?<query> or beyondfit://<path>?<query>
    // to a router location. Path comes through differently on the two schemes.
    final pathAndQuery = uri.path + (uri.hasQuery ? '?${uri.query}' : '');
    if (pathAndQuery.isEmpty) return;
    router.go(pathAndQuery.startsWith('/') ? pathAndQuery : '/$pathAndQuery');
  }

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
