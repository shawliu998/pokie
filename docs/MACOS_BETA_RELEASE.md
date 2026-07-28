# Qurio macOS beta release

Qurio currently has an Apple-silicon portfolio build with an embedded local runtime. The checked
release workflow is ready to produce a Developer ID signed, Apple-notarized DMG, but no build may be
described as notarized until that workflow completes with the project's Apple credentials.

## Required repository secrets

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`
- `APPLE_CERTIFICATE_PASSWORD`: password used when exporting the `.p12`
- `APPLE_SIGNING_IDENTITY`: the full Developer ID Application identity
- `APPLE_ID`: Apple account email used for notarization
- `APPLE_PASSWORD`: an app-specific Apple password
- `APPLE_TEAM_ID`: Apple Developer Team ID
- `KEYCHAIN_PASSWORD`: an ephemeral CI keychain password

Run the **macOS signed beta** workflow manually with the intended version. It installs locked
dependencies, imports the certificate into an ephemeral keychain, builds the embedded-runtime DMG,
lets Tauri submit and staple the notarization, then verifies the app and DMG before uploading them
with a SHA-256 checksum.

Without these secrets, the existing ad-hoc-signed build remains suitable only for supervised
evaluation. macOS may require explicit approval in Privacy & Security after download; it must not be
presented as a frictionless public release.
