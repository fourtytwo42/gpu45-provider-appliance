import { KeysManager } from "@/components/keys-manager";
import { ModelsWorkspaceNav } from "@/components/models-workspace-nav";
import { getEndpointSettings, listApiKeys } from "@/lib/api-keys";

export const dynamic = "force-dynamic";

export default async function KeysPage() {
  const [keys, settings] = await Promise.all([listApiKeys(), getEndpointSettings()]);
  return <div className="space-y-5"><ModelsWorkspaceNav /><KeysManager initialKeys={keys} initialAllowAnonymous={settings.allowAnonymous} /></div>;
}
