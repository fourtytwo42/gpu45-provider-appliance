import fs from "node:fs";
import Database from "better-sqlite3";
import type { ImageJob } from "./images";
import type { PocketTtsJob } from "./pocket-tts";
import type { TtsAudiobookJob, TtsModel, TtsPresentationJob, TtsSynthesisJob, TtsVoiceJob } from "./tts";
import type { VideoJob } from "./video";
import type { WhisperJob } from "./whisper";

type StoredJobHistory = {
  tts: {
    voiceJobs: TtsVoiceJob[];
    models: TtsModel[];
    synthesisJobs: TtsSynthesisJob[];
    audiobookJobs: TtsAudiobookJob[];
    presentationJobs: TtsPresentationJob[];
  };
  pocketTts: PocketTtsJob[];
  images: ImageJob[];
  videos: VideoJob[];
  whisper: WhisperJob[];
};

export function readPayloadRows<T>(dbPath: string, sql: string, params: unknown[] = []): T[] {
  if (!fs.existsSync(dbPath)) return [];
  const database = new Database(dbPath, { readonly: true, fileMustExist: true, timeout: 1_000 });
  try {
    database.pragma("busy_timeout = 1000");
    return (database.prepare(sql).all(...params) as Array<{ payload_json: string }>).flatMap((row) => {
      try { return [JSON.parse(row.payload_json) as T]; } catch { return []; }
    });
  } finally {
    database.close();
  }
}

function readJsonArray<T>(filePath: string): T[] {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return Array.isArray(value) ? value as T[] : [];
  } catch {
    return [];
  }
}

export function readStoredJobHistory(): StoredJobHistory {
  const ttsDb = process.env.GPU45_TTS_JOB_DB ?? "/models/qwen3-tts/api_data/jobs.db";
  const tts = <T>(store: string) => readPayloadRows<T>(ttsDb, "SELECT payload_json FROM records WHERE store_name=? ORDER BY position DESC LIMIT 250", [store]);
  return {
    tts: {
      voiceJobs: tts<TtsVoiceJob>("voice_jobs"),
      models: tts<TtsModel>("models"),
      synthesisJobs: tts<TtsSynthesisJob>("synthesis_jobs"),
      audiobookJobs: tts<TtsAudiobookJob>("audiobook_jobs"),
      presentationJobs: tts<TtsPresentationJob>("presentation_jobs"),
    },
    pocketTts: readJsonArray<PocketTtsJob>(process.env.GPU45_POCKET_TTS_JOBS ?? "/models/pocket-tts/data/jobs.json"),
    images: readPayloadRows<ImageJob>(process.env.GPU45_IMAGE_JOB_DB ?? "/models/image-gen/jobs.db", "SELECT payload_json FROM jobs ORDER BY position DESC LIMIT 250"),
    videos: readPayloadRows<VideoJob>(process.env.GPU45_VIDEO_JOB_DB ?? "/models/wan2-video/jobs.db", "SELECT payload_json FROM jobs ORDER BY position DESC LIMIT 250"),
    whisper: readPayloadRows<WhisperJob>(process.env.GPU45_WHISPER_JOB_DB ?? "/models/whisper/jobs.db", "SELECT payload_json FROM jobs ORDER BY position DESC LIMIT 250"),
  };
}
