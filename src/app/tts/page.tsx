import { Mic2 } from "lucide-react";
import { StudioShell } from "@/components/studio-shell";
import { TtsConsole } from "@/components/tts-console";
import { getTtsSnapshot } from "@/lib/tts";

export const dynamic = "force-dynamic";

export default async function TtsPage() {
  const snapshot = await getTtsSnapshot();
  return <StudioShell title="Audio Studio" eyebrow="TTS and audiobooks" description="Create voices, train voice models, synthesize speech, and convert long documents into resumable audiobooks." icon={Mic2} accent="#a78bfa" noticeTone="warning" noticeTitle="GPU-aware audio jobs" noticeBody="Voice training and GPU TTS may unload the LLM to free VRAM. Use Jobs to monitor progress and Outputs to retrieve generated audio."><TtsConsole initialSnapshot={snapshot} /></StudioShell>;
}
