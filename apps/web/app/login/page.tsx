import { loginProviders } from "@/auth";
import { PublicHome } from "@/components/public-home";
import { loginError, safeReturnPath } from "@/lib/login-policy";

export const dynamic = "force-dynamic";

export default async function Login({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  return <PublicHome providers={loginProviders} error={loginError(params.error)}
    returnTo={safeReturnPath(params.callbackUrl)} />;
}
