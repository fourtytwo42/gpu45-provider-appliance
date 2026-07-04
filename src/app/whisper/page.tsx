import { WhisperConsole } from "@/components/whisper-console";
import { getWhisperSnapshot } from "@/lib/whisper";

export const dynamic = "force-dynamic";

export default async function WhisperPage() {
  const snapshot = await getWhisperSnapshot();
  return <WhisperConsole initialSnapshot={snapshot} />;
}
