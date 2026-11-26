import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type CloudStatus } from "../api";
import { firebaseConfigured, signInWithGoogle } from "../lib/firebase";
import { relativeAgo } from "../lib/format";

export function syncLabel(s: CloudStatus, now = Date.now()): string {
  if (s.syncing) return "Syncing…";
  if (s.lastError) return "Sync failed";
  if (!s.lastSync) return "Not synced yet";
  return `Synced ${relativeAgo(s.lastSync, now)}`;
}

/** Header control for syncing with the StudyDeck phone app. Hidden until the cloud is set up. */
export function CloudSync({ signIn = signInWithGoogle }: { signIn?: typeof signInWithGoogle }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const status = useQuery({ queryKey: ["cloud-status"], queryFn: api.cloudStatus, refetchInterval: 60_000 });

  const afterSync = (s: CloudStatus) => {
    qc.setQueryData(["cloud-status"], s);
    // Reviews and attempts from the phone change queues, stats and history: refresh everything.
    qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "cloud-status" });
  };
  const sync = useMutation({
    mutationFn: api.cloudSync,
    onMutate: () => setError(null),
    onSuccess: (r) => afterSync(r.status),
    onError: (e: Error) => {
      setError(e.message);
      qc.invalidateQueries({ queryKey: ["cloud-status"] });
    },
  });
  const connect = useMutation({
    mutationFn: async () => {
      const { idToken, refreshToken } = await signIn();
      await api.cloudConnect(idToken, refreshToken);
      return api.cloudSync();
    },
    onMutate: () => setError(null),
    onSuccess: (r) => afterSync(r.status),
    onError: (e: Error) => {
      setError(e.message);
      qc.invalidateQueries({ queryKey: ["cloud-status"] });
    },
  });
  const disconnect = useMutation({
    mutationFn: api.cloudDisconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cloud-status"] }),
  });

  const s = status.data;
  if (!s?.configured || !firebaseConfigured) return null;

  if (!s.connected) {
    return (
      <div className="cloud">
        <button className="btn quiet" onClick={() => connect.mutate()} disabled={connect.isPending}>
          {connect.isPending ? "Connecting…" : "Connect phone"}
        </button>
        {error && (
          <span className="cloud-note error" role="alert">
            {error}
          </span>
        )}
      </div>
    );
  }

  const busy = sync.isPending || s.syncing;
  const problem = error ?? s.lastError;
  const shown = { ...s, syncing: busy, lastError: problem };
  return (
    <div className="cloud">
      <span className={`cloud-note${problem ? " error" : ""}`} aria-live="polite" title={problem ?? s.email ?? undefined}>
        {syncLabel(shown)}
        {!busy && s.pending > 0 && <span className="cloud-pending"> · {s.pending} to upload</span>}
      </span>
      <button className="btn quiet" onClick={() => sync.mutate()} disabled={busy}>
        Sync now
      </button>
      <button className="link cloud-off" onClick={() => disconnect.mutate()} disabled={busy}>
        Disconnect
      </button>
    </div>
  );
}
