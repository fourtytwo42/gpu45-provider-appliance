import { collectLiveTelemetry } from "@/lib/collectors";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      let closed = false;
      const close = () => {
        if (closed) return;
        closed = true;
        controller.close();
      };
      request.signal.addEventListener("abort", close);
      void (async () => {
        while (!closed) {
          try {
            const telemetry = await collectLiveTelemetry();
            if (!closed) controller.enqueue(encoder.encode(`event: telemetry\ndata: ${JSON.stringify(telemetry)}\n\n`));
          } catch (error) {
            if (!closed) controller.enqueue(encoder.encode(`event: error\ndata: ${JSON.stringify({ message: error instanceof Error ? error.message : "Telemetry failed" })}\n\n`));
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      })();
    },
    cancel() {},
  });
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
