import { WorkConsole } from "@/components/work-console";
import { getUnifiedJobs } from "@/lib/jobs";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const { jobs } = await getUnifiedJobs();
  return <WorkConsole jobs={jobs} />;
}
