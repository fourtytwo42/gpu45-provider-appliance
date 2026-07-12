import { LiveOverview } from "@/components/live-overview";
import { collectOverviewSnapshot } from "@/lib/collectors";
import { getEndpointSettings } from "@/lib/api-keys";
import { prisma } from "@/lib/db";
import { headers } from "next/headers";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [initial, settings, visibleModels, requestHeaders] = await Promise.all([
    collectOverviewSnapshot(),
    getEndpointSettings(),
    prisma.modelAsset.count({ where: { served: true } }),
    headers(),
  ]);
  const host = requestHeaders.get("host")?.replace(/:\d+$/, ":30001");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "http";
  const endpointBase = host ? `${protocol}://${host}` : initial.provider.providerUrl.replace(/\/$/, "");
  return <LiveOverview initial={initial} endpoint={{ allowAnonymous: settings.allowAnonymous, visibleModels, endpointBase }} />;
}
