import { Film } from "lucide-react";
import { StudioShell } from "@/components/studio-shell";
import { VideoConsole } from "@/components/video-console";
import { getStoredVideoSnapshot } from "@/lib/job-history";

export const dynamic = "force-dynamic";

export default async function VideoPage() {
  const snapshot = getStoredVideoSnapshot();
  return <StudioShell title="Media Studio" eyebrow="Video generation" description="Run local video models with explicit queue visibility, cancellation, and output access." icon={Film} accent="#f472b6" noticeTone="warning" noticeTitle="Video generation is exclusive GPU work" noticeBody="Video jobs can take over the GPU and pause the LLM provider. Start with preview presets and monitor progress from Jobs."><VideoConsole initialSnapshot={snapshot} /></StudioShell>;
}
