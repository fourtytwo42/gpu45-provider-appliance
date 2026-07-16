"use client";

import { useState } from "react";
import { AgenticBenchmarkConsole } from "./agentic-benchmark-console";
import { BenchmarkConsole } from "./benchmark-console";
import type { AgenticCampaign, AgenticModel, AgenticSuite } from "@/lib/agentic-benchmarks";
import type { BenchmarkRun, ModelAsset } from "@/lib/types";

type Props = { model: string; models: ModelAsset[]; initialRuns: BenchmarkRun[]; agenticModels: AgenticModel[]; agenticSuites: AgenticSuite[]; agenticCampaigns: AgenticCampaign[] };

export function BenchmarkWorkspace(props: Props) {
  const [tab, setTab] = useState<"throughput" | "agentic">("agentic");
  return <div className="space-y-5"><div className="flex border-b border-white/10"><button onClick={() => setTab("throughput")} className={`px-4 py-3 text-sm ${tab === "throughput" ? "border-b-2 border-cyan-400 text-white" : "text-slate-500 hover:text-slate-200"}`}>Throughput</button><button onClick={() => setTab("agentic")} className={`px-4 py-3 text-sm ${tab === "agentic" ? "border-b-2 border-cyan-400 text-white" : "text-slate-500 hover:text-slate-200"}`}>Agentic</button></div>{tab === "throughput" ? <BenchmarkConsole model={props.model} models={props.models} initialRuns={props.initialRuns} /> : <AgenticBenchmarkConsole initialModels={props.agenticModels} initialSuites={props.agenticSuites} initialCampaigns={props.agenticCampaigns} />}</div>;
}
