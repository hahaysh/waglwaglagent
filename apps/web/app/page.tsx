import { auth, authConfigured } from "@/auth";
import { Workspace } from "@/components/workspace";
import { isConnectionProvider } from "@/lib/connection-providers";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const provider = typeof params.connect === "string" && isConnectionProvider(params.connect) ? params.connect : undefined;
  const session = authConfigured ? await auth() : null;
  const user = session?.user?.id ? { id: session.user.id, name: session.user.name || "사용자" } : null;
  return <Workspace user={user} authConfigured={authConfigured} initialProvider={provider}
    connectionResult={typeof params.connection === "string" ? params.connection : undefined} />;
}
