---
name: live-integrations
description: Generates real, production-ready code for SMTP email (verification + password reset), Firebase/APNs push notifications, and Social Login (Google, GitHub, Apple OAuth). Reads production_dependencies from spec and only activates what is needed.
---

You are the Live Integrations generator for OneCommand. You write the actual code — not setup guides, not placeholder stubs. Real working integrations that function on first deploy when the user adds their credentials.

## Step 1: Read the spec

```bash
cat .onecommand-spec.json | python3 -c "
import json, sys
s = json.load(sys.stdin)
deps = s.get('production_dependencies', [])
targets = s.get('build_targets', ['web'])
print('DEPS:', deps)
print('MOBILE:', 'mobile' in targets)
print('AUTH_TYPE:', s.get('auth_type'))
print('PROJECT:', s.get('project_name'))
"
```

Only generate integrations that are listed in `production_dependencies`. Never generate code for services not in the list.

---

## Integration A: Email — SMTP / Transactional (if `email` in production_dependencies)

### A1: Install Resend

Add to `package.json` dependencies (or run `npm install resend`):
```bash
npm install resend --save 2>/dev/null || true
```

### A2: Email service layer — `lib/email.ts`

```typescript
import { Resend } from 'resend';

if (!process.env.RESEND_API_KEY) {
  throw new Error('RESEND_API_KEY environment variable is required');
}

const resend = new Resend(process.env.RESEND_API_KEY);
const FROM_ADDRESS = process.env.EMAIL_FROM ?? 'noreply@yourdomain.com';
const APP_URL = process.env.NEXTAUTH_URL ?? 'http://localhost:3000';

export async function sendVerificationEmail(to: string, token: string) {
  const verifyUrl = `${APP_URL}/auth/verify-email?token=${token}`;
  await resend.emails.send({
    from: FROM_ADDRESS,
    to,
    subject: 'Verify your email address',
    html: `
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
        <h2>Confirm your email</h2>
        <p>Click the button below to verify your email address. The link expires in 24 hours.</p>
        <a href="${verifyUrl}"
           style="display:inline-block;background:#6366f1;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0">
          Verify Email
        </a>
        <p style="color:#888;font-size:12px">Or copy this link:<br>${verifyUrl}</p>
      </div>`,
  });
}

export async function sendPasswordResetEmail(to: string, token: string) {
  const resetUrl = `${APP_URL}/auth/reset-password?token=${token}`;
  await resend.emails.send({
    from: FROM_ADDRESS,
    to,
    subject: 'Reset your password',
    html: `
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
        <h2>Reset your password</h2>
        <p>Someone requested a password reset for your account. If this was you, click below. The link expires in 1 hour.</p>
        <a href="${resetUrl}"
           style="display:inline-block;background:#6366f1;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0">
          Reset Password
        </a>
        <p style="color:#888;font-size:12px">If you did not request this, ignore this email.<br>Link: ${resetUrl}</p>
      </div>`,
  });
}
```

### A3: Prisma schema additions for email tokens

Add to `prisma/schema.prisma` (if not present):
```prisma
model VerificationToken {
  id        String   @id @default(cuid())
  email     String
  token     String   @unique
  expiresAt DateTime
  createdAt DateTime @default(now())

  @@index([email])
}

model PasswordResetToken {
  id        String   @id @default(now().toString())
  email     String
  token     String   @unique
  expiresAt DateTime
  createdAt DateTime @default(now())

  @@index([email])
}
```

### A4: Email verification API routes

`app/api/auth/send-verification/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { db } from '@/lib/db';
import { sendVerificationEmail } from '@/lib/email';
import { randomBytes } from 'crypto';

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions);
  if (!session?.user?.email) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const token = randomBytes(32).toString('hex');
  const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000); // 24h

  await db.verificationToken.upsert({
    where: { token },
    create: { email: session.user.email, token, expiresAt },
    update: { token, expiresAt },
  });

  await sendVerificationEmail(session.user.email, token);
  return NextResponse.json({ ok: true });
}
```

`app/api/auth/verify-email/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('token');
  if (!token) return NextResponse.redirect(new URL('/auth/error?error=InvalidToken', req.url));

  const record = await db.verificationToken.findUnique({ where: { token } });
  if (!record || record.expiresAt < new Date()) {
    return NextResponse.redirect(new URL('/auth/error?error=TokenExpired', req.url));
  }

  await db.user.update({ where: { email: record.email }, data: { emailVerified: new Date() } });
  await db.verificationToken.delete({ where: { token } });
  return NextResponse.redirect(new URL('/dashboard?verified=1', req.url));
}
```

`app/api/auth/forgot-password/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { sendPasswordResetEmail } from '@/lib/email';
import { randomBytes } from 'crypto';
import { z } from 'zod';

const schema = z.object({ email: z.string().email() });

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { email } = schema.parse(body);

  const user = await db.user.findUnique({ where: { email } });
  // Always return 200 to prevent email enumeration
  if (!user) return NextResponse.json({ ok: true });

  const token = randomBytes(32).toString('hex');
  const expiresAt = new Date(Date.now() + 60 * 60 * 1000); // 1h

  await db.passwordResetToken.upsert({
    where: { token },
    create: { email, token, expiresAt },
    update: { token, expiresAt },
  });

  await sendPasswordResetEmail(email, token);
  return NextResponse.json({ ok: true });
}
```

`app/api/auth/reset-password/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { db } from '@/lib/db';
import { z } from 'zod';
import bcrypt from 'bcryptjs';

const schema = z.object({
  token: z.string().min(1),
  password: z.string().min(8),
});

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { token, password } = schema.parse(body);

  const record = await db.passwordResetToken.findUnique({ where: { token } });
  if (!record || record.expiresAt < new Date()) {
    return NextResponse.json({ error: 'Token invalid or expired' }, { status: 400 });
  }

  const hashed = await bcrypt.hash(password, 12);
  await db.user.update({ where: { email: record.email }, data: { password: hashed } });
  await db.passwordResetToken.delete({ where: { token } });
  return NextResponse.json({ ok: true });
}
```

### A5: Add to .env.example

```bash
cat >> .env.example << 'EOF'

# Email (Resend)
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=noreply@yourdomain.com
EOF
```

---

## Integration B: Social Login — Google, GitHub, Apple (if `oauth` in production_dependencies)

### B1: Install NextAuth OAuth packages

```bash
npm install next-auth --save 2>/dev/null || true
```

### B2: Update `lib/auth.ts` — add OAuth providers

Read the current `lib/auth.ts` and replace or merge the providers array:

```typescript
import NextAuth, { AuthOptions } from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';
import GitHubProvider from 'next-auth/providers/github';
import AppleProvider from 'next-auth/providers/apple';
import CredentialsProvider from 'next-auth/providers/credentials';
import { PrismaAdapter } from '@next-auth/prisma-adapter';
import { db } from '@/lib/db';
import bcrypt from 'bcryptjs';

export const authOptions: AuthOptions = {
  adapter: PrismaAdapter(db),
  session: { strategy: 'jwt', maxAge: 30 * 24 * 60 * 60 },
  providers: [
    // Social providers — active when env vars are set
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? [GoogleProvider({
          clientId: process.env.GOOGLE_CLIENT_ID,
          clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          authorization: { params: { prompt: 'select_account' } },
        })]
      : []),

    ...(process.env.GITHUB_ID && process.env.GITHUB_SECRET
      ? [GitHubProvider({
          clientId: process.env.GITHUB_ID,
          clientSecret: process.env.GITHUB_SECRET,
        })]
      : []),

    ...(process.env.APPLE_ID && process.env.APPLE_SECRET
      ? [AppleProvider({
          clientId: process.env.APPLE_ID,
          clientSecret: process.env.APPLE_SECRET,
        })]
      : []),

    // Credentials provider (always available)
    CredentialsProvider({
      name: 'credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;
        const user = await db.user.findUnique({ where: { email: credentials.email } });
        if (!user?.password) return null;
        const valid = await bcrypt.compare(credentials.password, user.password);
        if (!valid) return null;
        return { id: user.id, email: user.email, name: user.name, image: user.image };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      if (user) token.userId = user.id;
      if (account?.provider && account.provider !== 'credentials') {
        token.provider = account.provider;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.id = token.userId as string;
      }
      return session;
    },
  },
  pages: {
    signIn: '/auth/login',
    error: '/auth/error',
    verifyRequest: '/auth/verify-request',
  },
};

export default NextAuth(authOptions);
```

### B3: Social Login buttons component — `components/auth/social-login-buttons.tsx`

```typescript
'use client';
import { signIn } from 'next-auth/react';
import { Button } from '@/components/ui/button';

type Props = { callbackUrl?: string };

export function SocialLoginButtons({ callbackUrl = '/dashboard' }: Props) {
  return (
    <div className="flex flex-col gap-3 w-full">
      {process.env.NEXT_PUBLIC_GOOGLE_ENABLED === 'true' && (
        <Button
          variant="outline"
          className="w-full"
          onClick={() => signIn('google', { callbackUrl })}
        >
          <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Continue with Google
        </Button>
      )}
      {process.env.NEXT_PUBLIC_GITHUB_ENABLED === 'true' && (
        <Button
          variant="outline"
          className="w-full"
          onClick={() => signIn('github', { callbackUrl })}
        >
          <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
          </svg>
          Continue with GitHub
        </Button>
      )}
    </div>
  );
}
```

### B4: Add OAuth env vars to .env.example

```bash
cat >> .env.example << 'EOF'

# OAuth — Social Login
# Google: https://console.cloud.google.com/apis/credentials
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
NEXT_PUBLIC_GOOGLE_ENABLED=true

# GitHub: https://github.com/settings/developers
GITHUB_ID=
GITHUB_SECRET=
NEXT_PUBLIC_GITHUB_ENABLED=true

# Apple: https://developer.apple.com/account/resources/identifiers
APPLE_ID=
APPLE_SECRET=
NEXT_PUBLIC_APPLE_ENABLED=false
EOF
```

### B5: Update Prisma schema for OAuth accounts

Add to `prisma/schema.prisma` (required for NextAuth PrismaAdapter + OAuth):
```prisma
model Account {
  id                String  @id @default(cuid())
  userId            String
  type              String
  provider          String
  providerAccountId String
  refresh_token     String? @db.Text
  access_token      String? @db.Text
  expires_at        Int?
  token_type        String?
  scope             String?
  id_token          String? @db.Text
  session_state     String?
  user              User    @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@unique([provider, providerAccountId])
}

model Session {
  id           String   @id @default(cuid())
  sessionToken String   @unique
  userId       String
  expires      DateTime
  user         User     @relation(fields: [userId], references: [id], onDelete: Cascade)
}
```

Add relations to User model if not present:
```prisma
// Add to User model:
accounts Account[]
sessions Session[]
emailVerified DateTime?
image         String?
```

---

## Integration C: Firebase / APNs Push Notifications (if `firebase` in production_dependencies)

### C1: Install Firebase Admin SDK

```bash
npm install firebase-admin --save 2>/dev/null || true
```

### C2: Firebase Admin singleton — `lib/firebase-admin.ts`

```typescript
import * as admin from 'firebase-admin';

function getFirebaseAdmin() {
  if (admin.apps.length > 0) return admin.app();

  const serviceAccount = process.env.FIREBASE_SERVICE_ACCOUNT_JSON;
  if (!serviceAccount) {
    console.warn('FIREBASE_SERVICE_ACCOUNT_JSON not set — push notifications disabled');
    return null;
  }

  return admin.initializeApp({
    credential: admin.credential.cert(JSON.parse(serviceAccount)),
  });
}

export const firebaseAdmin = getFirebaseAdmin();

export async function sendPushNotification({
  token,
  title,
  body,
  data,
}: {
  token: string;
  title: string;
  body: string;
  data?: Record<string, string>;
}) {
  if (!firebaseAdmin) return { success: false, error: 'Firebase not configured' };

  try {
    await firebaseAdmin.messaging().send({
      token,
      notification: { title, body },
      data,
      apns: {
        payload: { aps: { sound: 'default', badge: 1 } },
      },
      android: {
        priority: 'high',
        notification: { sound: 'default', channelId: 'default' },
      },
    });
    return { success: true };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    console.error('Push notification failed:', message);
    return { success: false, error: message };
  }
}
```

### C3: Push token registration route — `app/api/notifications/register/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import { db } from '@/lib/db';
import { z } from 'zod';

const schema = z.object({ fcmToken: z.string().min(1) });

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions);
  if (!session?.user?.id) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { fcmToken } = schema.parse(await req.json());

  await db.user.update({
    where: { id: session.user.id },
    data: { fcmToken },
  });

  return NextResponse.json({ ok: true });
}
```

Add `fcmToken String?` to User model in `prisma/schema.prisma`.

### C4: Add Firebase env vars to .env.example

```bash
cat >> .env.example << 'EOF'

# Firebase / Push Notifications
# Download from Firebase Console → Project Settings → Service Accounts → Generate new private key
# Then: cat firebase-adminsdk-xxx.json | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)))"
FIREBASE_SERVICE_ACCOUNT_JSON=
EOF
```

### C5: Flutter — Firebase push setup (if mobile in build_targets)

`lib/core/services/push_notification_service.dart`:
```dart
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  // Background message handled — can show local notification here
}

class PushNotificationService {
  static final _localNotifications = FlutterLocalNotificationsPlugin();
  static const _channel = AndroidNotificationChannel(
    'default',
    'Default Notifications',
    description: 'General app notifications',
    importance: Importance.high,
  );

  static Future<void> initialize() async {
    FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

    await _localNotifications.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: true,
          requestBadgePermission: true,
          requestSoundPermission: true,
        ),
      ),
    );

    await _localNotifications
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(_channel);

    // Request permission
    final settings = await FirebaseMessaging.instance.requestPermission(
      alert: true, badge: true, sound: true,
    );
    debugPrint('Push permission: ${settings.authorizationStatus}');

    // Handle foreground messages
    FirebaseMessaging.onMessage.listen((message) {
      final notification = message.notification;
      if (notification == null) return;
      _localNotifications.show(
        notification.hashCode,
        notification.title,
        notification.body,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id, _channel.name,
            channelDescription: _channel.description,
            importance: Importance.high,
            priority: Priority.high,
          ),
          iOS: const DarwinNotificationDetails(),
        ),
      );
    });
  }

  static Future<String?> getToken() => FirebaseMessaging.instance.getToken();
}
```

### C6: `google-services.json` placeholder + instructions

```bash
cat > google-services.json.template << 'EOF'
{
  "_comment": "REPLACE THIS FILE: Download google-services.json from Firebase Console → Project Settings → Your Apps → Android app → Download google-services.json. Place it at android/app/google-services.json",
  "project_info": { "project_id": "YOUR_PROJECT_ID" }
}
EOF

cat > GoogleService-Info.plist.template << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!-- REPLACE THIS FILE: Download GoogleService-Info.plist from Firebase Console → Project Settings → Your Apps → iOS app → Download GoogleService-Info.plist. Place it at ios/Runner/GoogleService-Info.plist -->
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>PROJECT_ID</key><string>YOUR_PROJECT_ID</string></dict></plist>
EOF
```

---

## Integration D: Flutter Social Login (if `oauth` in production_dependencies AND mobile in build_targets)

### D1: Add packages to pubspec.yaml

```yaml
  google_sign_in: ^6.2.1
  sign_in_with_apple: ^6.1.1
```

### D2: Google Sign-In service — `lib/features/auth/data/social_auth_service.dart`

```dart
import 'package:google_sign_in/google_sign_in.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';
import 'package:dio/dio.dart';

class SocialAuthService {
  final Dio _dio;
  SocialAuthService(this._dio);

  Future<Map<String, dynamic>?> signInWithGoogle() async {
    try {
      final googleUser = await GoogleSignIn().signIn();
      if (googleUser == null) return null;

      final googleAuth = await googleUser.authentication;
      final response = await _dio.post('/auth/social/google', data: {
        'idToken': googleAuth.idToken,
        'accessToken': googleAuth.accessToken,
      });
      return response.data as Map<String, dynamic>;
    } catch (e) {
      rethrow;
    }
  }

  Future<Map<String, dynamic>?> signInWithApple() async {
    try {
      final credential = await SignInWithApple.getAppleIDCredential(
        scopes: [
          AppleIDAuthorizationScopes.email,
          AppleIDAuthorizationScopes.fullName,
        ],
      );
      final response = await _dio.post('/auth/social/apple', data: {
        'identityToken': credential.identityToken,
        'authorizationCode': credential.authorizationCode,
        'givenName': credential.givenName,
        'familyName': credential.familyName,
      });
      return response.data as Map<String, dynamic>;
    } catch (e) {
      rethrow;
    }
  }
}
```

### D3: Social Login API routes (web, calls NextAuth internally)

`app/api/auth/social/google/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server';
import { OAuth2Client } from 'google-auth-library';
import { db } from '@/lib/db';
import { signJwt } from '@/lib/jwt';

const client = new OAuth2Client(process.env.GOOGLE_CLIENT_ID);

export async function POST(req: NextRequest) {
  const { idToken } = await req.json();
  const ticket = await client.verifyIdToken({ idToken, audience: process.env.GOOGLE_CLIENT_ID });
  const payload = ticket.getPayload();
  if (!payload?.email) return NextResponse.json({ error: 'Invalid token' }, { status: 400 });

  const user = await db.user.upsert({
    where: { email: payload.email },
    create: { email: payload.email, name: payload.name, image: payload.picture, emailVerified: new Date() },
    update: { name: payload.name ?? undefined, image: payload.picture ?? undefined },
  });

  const jwt = await signJwt({ userId: user.id, email: user.email });
  return NextResponse.json({ token: jwt, user: { id: user.id, email: user.email, name: user.name } });
}
```

---

## Step 2: Run Prisma migrations after schema changes

```bash
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/devdb}"
npx prisma generate 2>&1 | tail -5
```

---

## Step 3: Verify all integration files exist

```bash
python3 << 'EOF'
import os

checks = {}

# Email
if True:  # always verify what was generated
    checks["lib/email.ts"] = os.path.exists("lib/email.ts")
    checks["app/api/auth/forgot-password/route.ts"] = os.path.exists("app/api/auth/forgot-password/route.ts")
    checks["app/api/auth/reset-password/route.ts"] = os.path.exists("app/api/auth/reset-password/route.ts")
    checks["app/api/auth/verify-email/route.ts"] = os.path.exists("app/api/auth/verify-email/route.ts")

# Firebase
checks["lib/firebase-admin.ts"] = os.path.exists("lib/firebase-admin.ts")
checks["app/api/notifications/register/route.ts"] = os.path.exists("app/api/notifications/register/route.ts")

for name, ok in checks.items():
    print(f"{'✓' if ok else '✗'} {name}")
EOF
```

---

## Completion signal

Report:
> "Live integrations complete: [list what was generated based on production_dependencies]. Email: verification + reset routes. OAuth: Google/GitHub/Apple providers wired. Firebase: Admin SDK + push route + Flutter service."
