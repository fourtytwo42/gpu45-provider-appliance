import { FileText } from "lucide-react";
import { StudioShell } from "@/components/studio-shell";
import { WhisperConsole } from "@/components/whisper-console";
import { getWhisperSnapshot } from "@/lib/whisper";

export const dynamic = "force-dynamic";

export default async function WhisperPage() {
  const snapshot = await getWhisperSnapshot();
  return <StudioShell title="Audio Studio" eyebrow="Transcription" description="Convert audio and video files into transcript files while tracking progress and outputs across the appliance." icon={FileText} accent="#a78bfa" noticeTone="info" noticeTitle="Uploaded media is temporary" noticeBody="Transcription jobs keep transcript outputs, not source media. Monitor long jobs from Jobs and collect transcripts from Outputs."><WhisperConsole initialSnapshot={snapshot} /></StudioShell>;
}
