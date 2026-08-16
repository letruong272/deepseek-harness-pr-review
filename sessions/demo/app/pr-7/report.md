# Review PR #7 — Add Google sign-in and unify auth session handling

- Author: alice-dev | Base: main → Head: feat/google-signin
- Files changed: 8 | Commits: 2
## Verdict: PARTIAL

## Claims

| Claim | Content | Status | Evidence | Notes |
|---|---|---|---|---|
| C1 | Google Sign-In is wired into the existing /auth/mobile route by branching on idToken vs email/password, preserving the same response shape. | Matches | lib/features/auth/data/auth_api.dart:46-57, lib/core/session/session_controller.dart:132 | idToken sent to the same ApiPaths.login; AuthSession.fromApi parses both branches |
| C2 | The sign-in screen includes a 'Continue with Google' button. | Matches | lib/features/auth/ui/sign_in_screen.dart:236 | Continue with Google button with signin_google identifier |
| C3 | The logo layout bug is fixed: the logo no longer renders at full width. | Partial | lib/features/auth/ui/sign_in_screen.dart:128 | Uses Column instead of ListView, but the description claims width:56 was broken; base branch never had width:56 |
| C4 | The submit button is validated in real time based on form field state. | Matches | lib/features/auth/ui/sign_in_screen.dart:214 | Realtime listener on email/password; _canSubmit requires @ and non-empty password |
| C5 | Chat unread badge is fixed by moving the realtime listener into AppShell. | Matches | lib/features/shell/ui/app_shell.dart:206-220 | AppShell watches chatRealtimeProvider and conversationsProvider; badge updates from any tab |
| C6 | iOS Google Sign-In configuration is updated via GoogleService-Info.plist and Info.plist. | Unverified | - | GoogleService-Info.plist has CLIENT_ID, but Firebase project validity is outside this repo |

## Docs vs reality

| Doc | Status | Difference |
|---|---|---|
| docs/API.md | STALE | Documents email/password only; idToken branch is not mentioned |
| docs/CHAT.md | WRONG | Says unread count resets when opening the Chat tab; code now keeps the SSE listener alive in AppShell |
| docs/RELEASE.md | MATCH | Bundle ID and push config still accurate |

## Requirement impact

| Requirement | Impact | Detail |
|---|---|---|
| REQ-102 Google sign-in | CHANGED | New idToken branch in shared /auth/mobile; session/tenant commit identical to email login |
| REQ-88 Chat unread badge | CHANGED | Badge now updates from every tab; listener lifetime no longer tied to the Chat screen |
| REQ-45 Network usage | RISK | SSE + conversations provider are always watched after login, even when Chat is closed |

## Review threads

| Comment | Status | Notes |
|---|---|---|
| Missing validation: idToken branch ignores invalid token errors | STILL_VALID | No error mapping added for the Google branch in auth_api.dart |

## Confirmation log

- **Backend /auth/mobile accepts idToken?** → SKIPPED
- **docs/CHAT.md: code keeps SSE alive. Doc wrong?** → y
