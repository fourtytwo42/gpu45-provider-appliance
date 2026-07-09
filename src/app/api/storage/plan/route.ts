import { planStorageCleanup } from "@/lib/storage";
export async function POST(): Promise<Response> { return Response.json(await planStorageCleanup()); }
