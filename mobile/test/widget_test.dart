import 'package:flutter_test/flutter_test.dart';
import 'package:beyond_fit/main.dart';

void main() {
  testWidgets('App smoke test', (tester) async {
    await tester.pumpWidget(const BeyondFitApp());
    expect(find.byType(BeyondFitApp), findsOneWidget);
  });
}
