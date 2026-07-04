import { clearFinishedDownloadJobs, deleteDownloadJob, listDownloadJobs, queueDownloadBundle } from "@/lib/downloads";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json({ jobs: await listDownloadJobs() });
}


export async function DELETE(request: Request): Promise<Response> {
  const url = new URL(request.url);
  if (url.searchParams.get("finished") === "true") {
    return Response.json({ deleted: await clearFinishedDownloadJobs() });
  }
  const id = url.searchParams.get("id");
  if (!id) return Response.json({ error: "Download job id is required" }, { status: 400 });
  const deleted = await deleteDownloadJob(id);
  return Response.json(deleted ? { deleted: 1 } : { error: "Active or unknown download job cannot be removed" }, { status: deleted ? 200 : 409 });
}

export async function POST(request: Request): Promise<Response> {
  try {
    const bundle = await queueDownloadBundle(await request.json());
    return Response.json({ job: bundle.primary, companions: bundle.companions }, { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to queue download" }, { status: 400 });
  }
}
