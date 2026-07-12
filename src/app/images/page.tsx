import { ImageIcon } from "lucide-react";
import { StudioShell } from "@/components/studio-shell";
import { ImageConsole } from "@/components/image-console";
import { getStoredImageSnapshot } from "@/lib/job-history";

export const dynamic = "force-dynamic";

export default async function ImagesPage() {
  const snapshot = getStoredImageSnapshot();
  return <StudioShell title="Media Studio" eyebrow="Image generation" description="Generate images with tested local profiles and browse finished outputs from the shared library." icon={ImageIcon} accent="#f472b6" noticeTone="warning" noticeTitle="Image jobs own the GPU" noticeBody="Image rendering temporarily unloads the LLM, runs the GPU job, then restarts the provider when complete."><ImageConsole initialSnapshot={snapshot} /></StudioShell>;
}
