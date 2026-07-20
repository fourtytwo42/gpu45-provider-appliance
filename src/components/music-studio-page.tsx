import { Music2 } from "lucide-react";
import { getMusicSnapshot } from "@/lib/music";
import { MusicConsole } from "./music-console";
import { StudioShell } from "./studio-shell";

export async function MusicStudioPage() {
  const snapshot = await getMusicSnapshot();
  return (
    <StudioShell
      title="Music Studio"
      eyebrow="Song generation and editing"
      description="Create full songs, condition on reference audio, edit existing tracks, and separate stems with GPU-validated local models."
      icon={Music2}
      accent="#c084fc"
      activeHref="/studio/music"
      noticeTone="warning"
      noticeTitle="Music generation takes exclusive GPU ownership"
      noticeBody="The appliance pauses resumable speech work, yields low-priority benchmarks, unloads the LLM, generates the track, then restores the previous model and paused work."
    >
      <MusicConsole initialSnapshot={snapshot} />
    </StudioShell>
  );
}
