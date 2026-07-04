import { KeysManager } from "@/components/keys-manager";
import { getEndpointSettings, listApiKeys } from "@/lib/api-keys";

export const dynamic = "force-dynamic";

export default async function KeysPage() {
  const [keys, settings] = await Promise.all([listApiKeys(), getEndpointSettings()]);
  return <KeysManager initialKeys={keys} initialAllowAnonymous={settings.allowAnonymous} />;
}
