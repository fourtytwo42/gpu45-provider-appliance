import { Mic2 } from "lucide-react";
import { StudioShell } from "@/components/studio-shell";
import { TtsConsole, type TtsSection } from "@/components/tts-console";
import { getTtsSnapshot } from "@/lib/tts";

const copy: Record<TtsSection, { title: string; eyebrow: string; description: string }> = {
  speech: { title: "Speech", eyebrow: "Audio Studio", description: "Generate speech with a trained Qwen voice or lightweight Pocket TTS." },
  audiobooks: { title: "Audiobooks", eyebrow: "Audio Studio", description: "Turn long documents into resumable, quality-checked, sentence-aware narration." },
  presentations: { title: "Presentations", eyebrow: "Audio Studio", description: "Narrate PowerPoint speaker notes and produce an autoplay-ready deck." },
  voices: { title: "Voice Library", eyebrow: "Audio Studio", description: "Design or import reference voices and review the samples available for training." },
  training: { title: "Training", eyebrow: "Audio Studio", description: "Track and manage consistent trained voices for synthesis and long-form narration." },
};

export async function AudioStudioPage({ section }: { section: TtsSection }) {
  const snapshot = await getTtsSnapshot();
  const page = copy[section];
  return <StudioShell title={page.title} eyebrow={page.eyebrow} description={page.description} icon={Mic2} accent="#a78bfa" activeHref={`/studio/${section}`} noticeTone="warning" noticeTitle="Resource-aware audio" noticeBody="GPU audio pauses resumable work at a safe boundary and restores the previous LLM automatically. Pocket TTS remains CPU-only."><TtsConsole initialSnapshot={snapshot} section={section} /></StudioShell>;
}
