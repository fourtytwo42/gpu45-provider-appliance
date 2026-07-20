import { notFound, redirect } from "next/navigation";
import { AudioStudioPage } from "@/components/audio-studio-page";
import { MusicStudioPage } from "@/components/music-studio-page";
import type { TtsSection } from "@/components/tts-console";

export const dynamic = "force-dynamic";

const audioWorkflows = new Set<TtsSection>(["speech", "audiobooks", "presentations", "voices", "training"]);

export default async function StudioWorkflowPage({ params }: { params: Promise<{ workflow: string }> }) {
  const { workflow } = await params;
  if (audioWorkflows.has(workflow as TtsSection)) return <AudioStudioPage section={workflow as TtsSection} />;
  if (workflow === "music") return <MusicStudioPage />;
  if (workflow === "history") redirect("/outputs?type=audio");
  if (workflow === "transcription") redirect("/whisper");
  if (["images", "video", "research"].includes(workflow)) redirect(`/${workflow}`);
  notFound();
}
