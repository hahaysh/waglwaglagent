"use client";

import { Workspace } from "./workspace";
import type { ConnectionProvider } from "@/lib/connection-providers";

export function GuestWorkspace({ authConfigured, initialProvider }: {
  authConfigured: boolean; initialProvider?: ConnectionProvider;
}) {
  return <Workspace user={null} authConfigured={authConfigured} loginProvider="" sessionId=""
    initialProvider={initialProvider} onLogout={async () => undefined} />;
}
