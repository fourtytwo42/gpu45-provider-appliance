import { TtsConsole } from "@/components/tts-console";
import { getTtsSnapshot } from "@/lib/tts";

export const dynamic = "force-dynamic";

export default async function TtsPage() {
  const snapshot = await getTtsSnapshot();
  return <TtsConsole initialSnapshot={snapshot} />;
}
