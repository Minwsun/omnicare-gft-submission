import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return new Response("FORBIDDEN", { status: 403 });
  const { id } = await params;
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      for (let index = 0; index < 900; index += 1) {
        const run = await prisma.knowledgeIngestionRun.findUnique({ where: { id } });
        controller.enqueue(encoder.encode(`event: progress\ndata: ${JSON.stringify(run || { status: "NOT_FOUND" })}\n\n`));
        if (!run || ["DONE", "CANCELLED", "QUARANTINED"].includes(run.status)) break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      controller.close();
    },
  });
  return new Response(stream, { headers: { "content-type": "text/event-stream", "cache-control": "no-cache, no-transform", connection: "keep-alive" } });
}
