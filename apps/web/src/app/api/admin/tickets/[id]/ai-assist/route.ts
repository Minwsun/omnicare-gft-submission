import { NextResponse } from "next/server";
import { createHash } from "node:crypto";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const ticket = await prisma.ticket.findUnique({ where: { id }, include: { customer: true, order: { include: { items: true, shipments: true, payments: true, refunds: true } }, events: { orderBy: { createdAt: "desc" }, take: 20 }, conversation: { include: { memory: true, messages: { orderBy: { createdAt: "desc" }, take: 12 }, aiRuns: { orderBy: { startedAt: "desc" }, take: 3, include: { toolCalls: true, retrievals: true } } } } } });
  if (!ticket) return NextResponse.json({ error: "TICKET_NOT_FOUND" }, { status: 404 });
  const messages = ticket.conversation.messages.slice().reverse().map((message) => ({ id: message.id, direction: message.direction, source: (message.metadata as { source?: string } | null)?.source, content: message.content, createdAt: message.createdAt }));
  const latestInbound = [...messages].reverse().find((message) => message.direction === "INBOUND");
  const contextVersion = createHash("sha256").update(JSON.stringify({ ticketId: ticket.id, status: ticket.status, updatedAt: ticket.updatedAt, latestInboundId: latestInbound?.id, orderUpdatedAt: ticket.order?.updatedAt, memoryVersion: ticket.conversation.memory?.version })).digest("hex").slice(0, 24);
  const cached = ticket.events.find((event) => event.type === "AI_ASSIST_CACHED" && (event.payload as { contextVersion?: string } | null)?.contextVersion === contextVersion);
  if (cached) return NextResponse.json((cached.payload as { result: object }).result);
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });
  const response = await fetch(`${serviceUrl}/admin/assist`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ticket_id: ticket.id, category: ticket.category, priority: ticket.priority, summary: ticket.summary, customer: ticket.customer, order: ticket.order, conversation: messages, memory: ticket.conversation.memory, evidence: ticket.conversation.aiRuns.flatMap((run) => [...run.toolCalls, ...run.retrievals]), context_version: contextVersion }), cache: "no-store" });
  if (!response.ok) return NextResponse.json({ error: "AI_ASSIST_UNAVAILABLE" }, { status: 503 });
  const result = { ...(await response.json()), contextVersion };
  await prisma.ticketEvent.create({ data: { ticketId: ticket.id, type: "AI_ASSIST_CACHED", payload: { contextVersion, result } } });
  return NextResponse.json(result);
}
