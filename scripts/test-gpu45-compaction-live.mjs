const endpoint = process.env.GPU45_RESPONSES_URL || 'http://192.168.50.189:30001/v1/responses';
const model = process.env.GPU45_MODEL || 'Qwen3.8-27B-UD-Q5_K_XL-262K';
const marker = 'BLUE-COMET-7319';

async function responses(input, maxOutputTokens = 256) {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model, input, stream: true, max_output_tokens: maxOutputTokens }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  const body = await response.text();
  const events = body
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data: '))
    .map((line) => JSON.parse(line.slice(6)));
  const completed = events.findLast((event) => event.type === 'response.completed');
  if (!completed) throw new Error('stream did not contain response.completed');
  return completed.response;
}

const compacted = await responses([
  {
    type: 'message',
    role: 'user',
    content: [{
      type: 'input_text',
      text: `Remember the exact marker ${marker}. The pending action is validate continuity after compaction.`,
    }],
  },
  { type: 'compaction_trigger' },
]);

if (compacted.output?.length !== 1 || compacted.output[0]?.type !== 'compaction') {
  throw new Error(`expected exactly one compaction output item: ${JSON.stringify(compacted.output)}`);
}

const continued = await responses([
  compacted.output[0],
  {
    type: 'message',
    role: 'user',
    content: [{ type: 'input_text', text: 'State the exact marker and pending action in one sentence.' }],
  },
], 1024);
const answer = (continued.output || [])
  .flatMap((item) => item.type === 'message' ? item.content || [] : [])
  .filter((item) => item.type === 'output_text')
  .map((item) => item.text || '')
  .join('\n');

if (!answer.includes(marker) || !answer.toLowerCase().includes('validate continuity')) {
  throw new Error(`continuity assertion failed: ${answer}`);
}

console.log(JSON.stringify({
  ok: true,
  model,
  compactionItemCount: compacted.output.length,
  terminalStatus: compacted.status,
  continuityAnswer: answer,
}, null, 2));
