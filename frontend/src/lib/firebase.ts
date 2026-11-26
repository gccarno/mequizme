/** Google sign-in for phone sync. The browser only signs in; it hands the tokens to the local
 * backend, which does the syncing, then signs out here so only one session exists.
 * Firebase is imported lazily: nobody pays for it until they click "Connect". */

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
};

export const firebaseConfigured = Boolean(config.apiKey && config.projectId);

export interface GoogleSession {
  idToken: string;
  refreshToken: string;
}

export async function signInWithGoogle(): Promise<GoogleSession> {
  if (!firebaseConfigured) throw new Error("Firebase isn't configured; see infra/README.md");
  const [{ initializeApp, getApps }, { getAuth, GoogleAuthProvider, signInWithPopup, signOut }] = await Promise.all([
    import("firebase/app"),
    import("firebase/auth"),
  ]);
  const app = getApps()[0] ?? initializeApp(config);
  const auth = getAuth(app);
  const { user } = await signInWithPopup(auth, new GoogleAuthProvider());
  const session = { idToken: await user.getIdToken(), refreshToken: user.refreshToken };
  await signOut(auth); // local only: the refresh token we hand over stays valid
  return session;
}
