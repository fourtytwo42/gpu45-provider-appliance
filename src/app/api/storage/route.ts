import { getStorageInventory } from "@/lib/storage";
export const dynamic = "force-dynamic";
export async function GET(): Promise<Response> { return Response.json(await getStorageInventory()); }
