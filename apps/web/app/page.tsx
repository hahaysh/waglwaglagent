import { auth, authConfigured } from "@/auth";
import { Workspace } from "@/components/workspace";

export const dynamic = "force-dynamic";

export default async function Home() {
  const session = authConfigured ? await auth() : null;
  const user = session?.user?.id ? { id: session.user.id, name: session.user.name || "사용자" } : null;
  return <Workspace user={user} authConfigured={authConfigured} />;
}
