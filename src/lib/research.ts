import crypto from "node:crypto";
import dns from "node:dns/promises";
import { isIP } from "node:net";
import { JSDOM } from "jsdom";
import { Readability } from "@mozilla/readability";
import { prisma } from "./db";
import { getConfig } from "./config";

export type SearchCategory = "general" | "jobs";
export type RenderMode = false | "auto" | true;

const BLOCKED_JOB_DOMAINS = [
  "linkedin.com",
  "indeed.com",
  "ziprecruiter.com",
  "dice.com",
  "otta.com",
  "wellfound.com",
  "monster.com",
  "glassdoor.com",
  "careerbuilder.com",
  "simplyhired.com",
];

const ATS_DOMAINS = [
  "greenhouse.io",
  "lever.co",
  "ashbyhq.com",
  "myworkdayjobs.com",
  "workdayjobs.com",
  "smartrecruiters.com",
  "bamboohr.com",
  "jobvite.com",
];

const MAX_FETCH_BYTES = 3_000_000;
const FETCH_TIMEOUT_MS = 15_000;
const USER_AGENT = "GPU45ResearchBot/0.1 (+local appliance research; respectful rate limited)";
const recentDomainFetches = new Map<string, number>();

function id(prefix: string, value?: string): string {
  const input = value ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}_${crypto.createHash("sha256").update(input).digest("hex").slice(0, 24)}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

function hostOf(rawUrl: string): string {
  return new URL(rawUrl).hostname.toLowerCase().replace(/^www\./, "");
}

function isPrivateIp(address: string): boolean {
  if (address === "::1" || address === "127.0.0.1") return true;
  if (address.startsWith("10.")) return true;
  if (address.startsWith("192.168.")) return true;
  if (/^172\.(1[6-9]|2\d|3[0-1])\./.test(address)) return true;
  if (/^169\.254\./.test(address)) return true;
  if (/^fc|^fd/i.test(address)) return true;
  if (/^fe80:/i.test(address)) return true;
  return false;
}

export async function validatePublicHttpUrl(rawUrl: string): Promise<URL> {
  const parsed = new URL(rawUrl);
  if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Only http and https URLs are allowed.");
  if (!parsed.hostname) throw new Error("URL must include a host.");
  if (isIP(parsed.hostname) && isPrivateIp(parsed.hostname)) throw new Error("Private and local IP URLs are blocked.");
  const addresses = await dns.lookup(parsed.hostname, { all: true }).catch(() => []);
  for (const entry of addresses) {
    if (isPrivateIp(entry.address)) throw new Error("Host resolves to a private or local address and is blocked.");
  }
  return parsed;
}

function isLikelyOfficial(url: string): boolean {
  const host = hostOf(url);
  if (BLOCKED_JOB_DOMAINS.some((domain) => host === domain || host.endsWith(`.${domain}`))) return false;
  return true;
}

function atsType(url: string): string | null {
  const host = hostOf(url);
  const match = ATS_DOMAINS.find((domain) => host === domain || host.endsWith(`.${domain}`));
  if (!match) return null;
  if (match.includes("greenhouse")) return "greenhouse";
  if (match.includes("lever")) return "lever";
  if (match.includes("ashby")) return "ashby";
  if (match.includes("workday")) return "workday";
  return match.split(".")[0];
}

function resultConfidence(url: string): number {
  if (!isLikelyOfficial(url)) return 0.05;
  if (atsType(url)) return 0.9;
  const lower = url.toLowerCase();
  if (lower.includes("career") || lower.includes("jobs") || lower.includes("opening")) return 0.72;
  return 0.5;
}

function normalizeSearxResult(item: Record<string, unknown>, rank: number) {
  return {
    title: String(item.title ?? item.pretty_url ?? item.url ?? "Untitled result"),
    url: String(item.url ?? ""),
    snippet: String(item.content ?? item.snippet ?? ""),
    engine: Array.isArray(item.engines) ? item.engines.join(",") : String(item.engine ?? "searxng"),
    rank: rank + 1,
  };
}

export async function searchWeb(query: string, category: SearchCategory = "general", limit = 10) {
  const cfg = getConfig();
  const cleanQuery = query.trim();
  if (!cleanQuery) throw new Error("Search query is required.");
  const runId = id("wsr");
  await prisma.webSearchRun.create({ data: { id: runId, query: cleanQuery, category, resultCount: 0, status: "running", createdAt: new Date() } });
  try {
    const params = new URLSearchParams({ q: cleanQuery, format: "json", safesearch: "1", language: "en" });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const response = await fetch(`${cfg.searxngUrl.replace(/\/$/, "")}/search?${params}`, { signal: controller.signal, headers: { Accept: "application/json", "User-Agent": USER_AGENT } });
    clearTimeout(timeout);
    if (!response.ok) throw new Error(`SearXNG returned ${response.status}: ${await response.text()}`);
    const data = await response.json() as { results?: Array<Record<string, unknown>> };
    const results = (data.results ?? []).map(normalizeSearxResult).filter((item) => item.url).slice(0, Math.max(1, Math.min(limit, 25)));
    await prisma.webSearchResult.createMany({
      data: results.map((item, index) => ({
        id: id("ws", `${runId}-${item.url}`),
        runId,
        title: item.title,
        url: item.url,
        snippet: item.snippet,
        engine: item.engine,
        rank: index + 1,
        officialSource: category === "jobs" ? isLikelyOfficial(item.url) : true,
      })),
    });
    await prisma.webSearchRun.update({ where: { id: runId }, data: { resultCount: results.length, status: "completed" } });
    return { run: { id: runId, query: cleanQuery, category, resultCount: results.length, status: "completed", createdAt: nowIso() }, results };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await prisma.webSearchRun.update({ where: { id: runId }, data: { status: "failed", error: message } });
    throw error;
  }
}

async function robotsAllowed(url: URL): Promise<boolean> {
  try {
    const robotsUrl = new URL("/robots.txt", url.origin);
    const response = await fetch(robotsUrl, { headers: { "User-Agent": USER_AGENT }, signal: AbortSignal.timeout(4000) });
    if (!response.ok) return true;
    const text = await response.text();
    const path = url.pathname || "/";
    let applies = false;
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.split("#")[0].trim();
      if (!line) continue;
      const [key, ...rest] = line.split(":");
      const value = rest.join(":").trim();
      if (/^user-agent$/i.test(key)) applies = value === "*" || value.toLowerCase().includes("gpu45");
      if (applies && /^disallow$/i.test(key) && value && path.startsWith(value)) return false;
    }
    return true;
  } catch {
    return true;
  }
}

function enforceRateLimit(host: string): void {
  const last = recentDomainFetches.get(host) ?? 0;
  const elapsed = Date.now() - last;
  if (elapsed < 1500) throw new Error(`Rate limited for ${host}; retry in ${Math.ceil((1500 - elapsed) / 1000)}s.`);
  recentDomainFetches.set(host, Date.now());
}

function extractLinks(document: Document, baseUrl: string) {
  const links: Array<{ text: string; url: string }> = [];
  for (const anchor of Array.from(document.querySelectorAll("a[href]"))) {
    const href = anchor.getAttribute("href");
    if (!href) continue;
    try {
      links.push({ text: (anchor.textContent ?? "").trim().slice(0, 180), url: new URL(href, baseUrl).toString() });
    } catch {}
  }
  return links.slice(0, 300);
}

function extractReadable(html: string, url: string) {
  const dom = new JSDOM(html, { url });
  const reader = new Readability(dom.window.document);
  const article = reader.parse();
  const title = article?.title || dom.window.document.title || url;
  const text = (article?.textContent || dom.window.document.body?.textContent || "").replace(/\s+\n/g, "\n").replace(/[ \t]{2,}/g, " ").trim();
  const links = extractLinks(dom.window.document, url);
  return { title, text: text.slice(0, 200_000), links };
}

export async function fetchUrl(rawUrl: string, render: RenderMode = false, extractLinksFlag = true) {
  const parsed = await validatePublicHttpUrl(rawUrl);
  const host = hostOf(parsed.toString());
  enforceRateLimit(host);
  const allowed = await robotsAllowed(parsed);
  if (!allowed) throw new Error("robots.txt disallows fetching this URL.");
  const cached = await prisma.webPageCache.findFirst({ where: { url: parsed.toString() }, orderBy: { fetchedAt: "desc" } });
  if (cached && Date.now() - new Date(cached.fetchedAt).getTime() < 1000 * 60 * 30) {
    return { page: cached, text: cached.text, links: JSON.parse(cached.linksJson || "[]"), cached: true };
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  const response = await fetch(parsed, { redirect: "follow", signal: controller.signal, headers: { "User-Agent": USER_AGENT, Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5" } });
  clearTimeout(timeout);
  const contentType = response.headers.get("content-type") ?? "";
  if (!/text\/html|application\/xhtml\+xml|text\/plain|application\/json/.test(contentType)) throw new Error(`Unsupported content type: ${contentType || "unknown"}`);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body returned.");
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (!value) continue;
    size += value.byteLength;
    if (size > MAX_FETCH_BYTES) throw new Error("Response exceeded maximum fetch size.");
    chunks.push(value);
  }
  const html = Buffer.concat(chunks).toString("utf8");
  const extracted = contentType.includes("html") ? extractReadable(html, response.url) : { title: response.url, text: html.slice(0, 200_000), links: [] };
  const links = extractLinksFlag ? extracted.links : [];
  const page = await prisma.webPageCache.create({
    data: {
      id: id("wpc", `${response.url}-${Date.now()}`),
      url: parsed.toString(),
      finalUrl: response.url,
      statusCode: response.status,
      contentType,
      fetchedAt: new Date(),
      title: extracted.title,
      text: extracted.text,
      linksJson: JSON.stringify(links),
      robotsAllowed: allowed,
      renderMode: render === true ? "render" : render === "auto" ? "auto-static" : "static",
    },
  });
  return { page, text: page.text, links, cached: false };
}

function textMatch(text: string, patterns: RegExp[]): string | null {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return match[1].trim().slice(0, 300);
  }
  return null;
}

export async function extractJob(rawUrl: string, render: RenderMode = "auto") {
  const fetched = await fetchUrl(rawUrl, render, true);
  const page = fetched.page;
  const text = fetched.text || "";
  const url = page.finalUrl || page.url;
  const title = textMatch(text, [/Job Title\s*[:\-]\s*(.+)/i, /^([^\n]{4,120}(Engineer|Developer|Architect|SRE|DevOps|AI|ML)[^\n]*)/im]) || page.title || "Unknown role";
  const company = textMatch(text, [/Company\s*[:\-]\s*(.+)/i, /at\s+([A-Z][A-Za-z0-9 .,&-]{2,80})/]) || hostOf(url).split(".")[0];
  const location = textMatch(text, [/Location\s*[:\-]\s*(.+)/i, /(Remote[^\n,.]*)/i]) || "unknown";
  const remoteStatus = /remote|united states|usa|u\.s\./i.test(`${location}\n${text.slice(0, 4000)}`) ? "remote-or-us-mentioned" : "unknown";
  const links = fetched.links as Array<{ text: string; url: string }>;
  const apply = links.find((link) => /apply|application|submit/i.test(`${link.text} ${link.url}`))?.url || url;
  const blocked = !isLikelyOfficial(url);
  const lead = await prisma.jobLead.create({
    data: {
      id: id("job", url),
      sourceUrl: url,
      company,
      title,
      location,
      remoteStatus,
      applyUrl: apply,
      atsType: atsType(url),
      confidence: blocked ? 0.05 : resultConfidence(url),
      extractedJson: JSON.stringify({ description: text.slice(0, 12000), links: links.slice(0, 50), blockedJobBoard: blocked }),
      createdAt: new Date(),
    },
  });
  return { lead, page };
}

export async function searchJobs(query: string, remoteOnly = true, officialOnly = true, limit = 10) {
  const enrichedQuery = `${query} ${remoteOnly ? "remote OR \"United States\" " : ""} careers jobs apply`;
  const search = await searchWeb(enrichedQuery, "jobs", Math.min(limit * 3, 25));
  const rejected: Array<{ url: string; reason: string }> = [];
  const leads = [];
  for (const result of search.results) {
    if (!isLikelyOfficial(result.url)) {
      rejected.push({ url: result.url, reason: "blocked public job board or repost source" });
      continue;
    }
    if (officialOnly && resultConfidence(result.url) < 0.5) {
      rejected.push({ url: result.url, reason: "low official-source confidence" });
      continue;
    }
    try {
      const extracted = await extractJob(result.url, "auto");
      if (remoteOnly && extracted.lead.remoteStatus === "unknown") {
        rejected.push({ url: result.url, reason: "remote/US signal not found" });
        continue;
      }
      leads.push(extracted.lead);
      if (leads.length >= limit) break;
    } catch (error) {
      rejected.push({ url: result.url, reason: error instanceof Error ? error.message : String(error) });
    }
  }
  return { run: search.run, leads, rejected };
}

export async function researchHistory(kind: string, limit = 30) {
  const take = Math.max(1, Math.min(limit, 100));
  if (kind === "page") return { pages: await prisma.webPageCache.findMany({ orderBy: { fetchedAt: "desc" }, take }) };
  if (kind === "job") return { jobs: await prisma.jobLead.findMany({ orderBy: { createdAt: "desc" }, take }) };
  return { searches: await prisma.webSearchRun.findMany({ orderBy: { createdAt: "desc" }, take, include: { results: { take: 5, orderBy: { rank: "asc" } } } }) };
}
