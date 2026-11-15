import { siteSession, authConfigured, loginProviders } from "@/auth";
import { GuestWorkspace } from "@/components/guest-workspace";
import { PersonalWorkspace } from "@/components/personal-workspace";
import { PublicHome } from "@/components/public-home";
import { isConnectionProvider } from "@/lib/connection-providers";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const provider = typeof params.connect === "string" && isConnectionProvider(params.connect) ? params.connect : undefined;
  let session;
  try { session = authConfigured ? await siteSession() : null; }
  catch {
    console.error("Site session storage unavailable");
    return <PublicHome providers={loginProviders}
      error="계정 저장소에 접근할 수 없습니다. 잠시 후 다시 시도해주세요." />;
  }
  if (!session?.user?.id || !session.sessionId) return <GuestWorkspace authConfigured={authConfigured} initialProvider={provider} />;
  return <PersonalWorkspace session={session} initialProvider={provider}
    connectionResult={typeof params.connection === "string" ? params.connection : undefined} />;
}
