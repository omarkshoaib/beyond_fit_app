# Deep-link well-known files

These two files must be hosted at `beyondfit.app` (or whatever production
domain replaces it) for iOS Universal Links and Android App Links to work.

## Hosting requirements

| File | URL it must resolve at | Content-Type |
|---|---|---|
| `apple-app-site-association` | `https://beyondfit.app/.well-known/apple-app-site-association` | `application/json` (no `.json` extension) |
| `assetlinks.json` | `https://beyondfit.app/.well-known/assetlinks.json` | `application/json` |

Both files must be served over HTTPS with no redirects.

## Before going live

1. **iOS** — replace `TEAMID` in `apple-app-site-association` with your Apple Developer Team ID (looks like `9X4ABC123D`).
2. **Android** — replace `REPLACE_WITH_RELEASE_KEYSTORE_SHA256_FINGERPRINT` in `assetlinks.json` with the SHA-256 fingerprint of your release keystore. Get it via:
   ```bash
   keytool -list -v -keystore /path/to/release.keystore -alias <alias> | grep SHA256
   ```
3. Deploy both files to the production web host (e.g. behind a static-file CDN or your reverse proxy).
4. Verify:
   - iOS: https://branch.io/resources/aasa-validator/
   - Android: `adb shell pm verify-app-links --re-verify com.beyondfit.beyond_fit`

Until those files are hosted, deep links fall back to the custom `beyondfit://` scheme registered in `AndroidManifest.xml` and `Info.plist`.
