import { NextResponse } from "next/server";
import { z } from "zod";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { loadConversationContext, persistConversationMemory } from "@/lib/conversation-memory";
import { addTicketEvent, findActiveTicket, publicHandoffState } from "@/lib/handoff";

const requestSchema = z.object({
  content: z.string().trim().max(8000).default(""),
  attachmentIds: z.array(z.string().min(1)).max(5).default([]),
  conversationId: z.string().uuid().optional(),
  messageId: z.string().uuid().optional(),
  channel: z.enum(["WEB", "EMAIL"]).default("WEB"),
  pageContext: z.object({
    route: z.string().max(500),
    orderId: z.string().max(80).optional(),
  }).optional(),
}).refine((value) => value.content.length > 0 || value.attachmentIds.length > 0, { message: "MESSAGE_OR_ATTACHMENT_REQUIRED" });

export async function POST(request: Request) {
  const startedAt=performance.now();
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  if (!user.customerId) return NextResponse.json({ error: "CUSTOMER_PROFILE_REQUIRED" }, { status: 403 });
  const customerId = user.customerId;
  const parsed = requestSchema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_MESSAGE" }, { status: 400 });
  const payload = parsed.data;
  let conversationId = payload.conversationId;
  let conversationTitle: string | null = null;
  const messageId = payload.messageId ?? crypto.randomUUID();
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });

  if (conversationId) {
    const owned = await prisma.conversation.findFirst({ where: { id: conversationId, customerId, channel: payload.channel } });
    if (!owned) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
    conversationTitle = owned.title;
  } else {
    conversationId = crypto.randomUUID();
    await prisma.conversation.create({ data: { id: conversationId, customerId, channel: payload.channel } });
  }
  if (!conversationId) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  const attachmentRows = payload.attachmentIds.length ? await prisma.chatAttachment.findMany({ where: { id: { in: payload.attachmentIds }, conversationId, customerId, messageId: null, deletedAt: null }, select: { id: true, fileName: true, mimeType: true, size: true, bytes: true, analysis: true } }) : [];
  if (attachmentRows.length !== payload.attachmentIds.length) return NextResponse.json({ error: "INVALID_ATTACHMENTS" }, { status: 400 });
  const pending = attachmentRows.filter((item) => !item.analysis && item.bytes);
  if (pending.length) {
    const visionResponse = await fetch(`${serviceUrl}/vision/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        message: payload.content,
        order_context: payload.pageContext ?? {},
        images: pending.map((item) => ({ file_name: item.fileName, mime_type: item.mimeType, data_url: `data:${item.mimeType};base64,${Buffer.from(item.bytes!).toString("base64")}` })),
      }),
      cache: "no-store",
    });
    if (!visionResponse.ok) return NextResponse.json({ error: "VISION_ANALYSIS_UNAVAILABLE", handoff: true }, { status: 503 });
    const analyses = await visionResponse.json() as unknown[];
    await prisma.$transaction(pending.map((item, index) => prisma.chatAttachment.update({ where: { id: item.id }, data: { analysis: analyses[index] as object, status: "ANALYZED" } })));
    pending.forEach((item, index) => { item.analysis = analyses[index] as object; });
  }
  const attachments = attachmentRows.map(({ bytes: _, ...item }) => item);
  const content = payload.content || "Tôi gửi ảnh kiện hàng.";
  const [,pageContext]=await Promise.all([
    prisma.$transaction([
      prisma.message.create({ data: { id: messageId, conversationId, direction: "INBOUND", content, metadata: attachments.length ? { attachments } : undefined } }),
      prisma.chatAttachment.updateMany({ where: { id: { in: payload.attachmentIds } }, data: { messageId, status: "ATTACHED" } }),
      prisma.conversation.update({ where: { id: conversationId }, data: { title: conversationTitle ?? content.slice(0, 72), lastMessageAt: new Date() } }),
    ]),
    loadConversationContext(conversationId, customerId, payload.pageContext ?? {}),
  ]);

  const activeTicket = await findActiveTicket(conversationId);
  if (activeTicket) {
    await addTicketEvent(activeTicket.id, "CUSTOMER_REPLIED", { messageId });
    if (activeTicket.status === "PENDING_CUSTOMER") {
      await prisma.ticket.update({ where: { id: activeTicket.id }, data: { status: "NEED_HUMAN" } });
    }
    const handoff = publicHandoffState({ ...activeTicket, status: activeTicket.status === "PENDING_CUSTOMER" ? "NEED_HUMAN" : activeTicket.status });
    const body = `event: done\ndata: ${JSON.stringify({ answer: "", confidence: 1, requires_human: true, handoff, citations: [], tool_calls: [], ui: [] })}\n\n`;
    return new Response(body, { headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache, no-transform", "x-conversation-id": conversationId } });
  }

  const upstream = await fetch(`${serviceUrl}/agent/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message_id: messageId, content, customer_id: customerId, actor_role: user.role, channel: payload.channel, conversation_id: conversationId, page_context: { ...pageContext, attachments } }),
    cache: "no-store",
  });
  if (!upstream.ok || !upstream.body) return NextResponse.json({ error: "AGENT_STREAM_UNAVAILABLE", handoff: true }, { status: 503 });
  const decoder = new TextDecoder();
  let buffer = "";
  let persisted = false;
  const stream = upstream.body.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    async transform(chunk, controller) {
      controller.enqueue(chunk);
      buffer += decoder.decode(chunk, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        if (persisted || !block.startsWith("event: done")) continue;
        const raw = block.match(/^data: (.+)$/m)?.[1];
        if (!raw) continue;
        const result = JSON.parse(raw);
        if (result.intent === "HUMAN_REQUEST" || result.handoff_requested) {
          result.handoff_requested = true;
          result.requires_human = true;
          result.escalation_reason ||= "CUSTOMER_REQUEST";
        }
        if (result.requires_human && !await findActiveTicket(conversationId)) {
          const ticket = await prisma.ticket.create({ data: { id: `TCK-${crypto.randomUUID().slice(0, 12).toUpperCase()}`, customerId, conversationId, status: "NEED_HUMAN", priority: result.priority ?? "MEDIUM", category: result.category ?? result.intent ?? "CUSTOMER_REQUEST", summary: result.escalation_reason === "CUSTOMER_REQUEST" ? "Khách hàng yêu cầu gặp nhân viên" : result.answer.slice(0, 500) } });
          await addTicketEvent(ticket.id, "AI_HANDOFF_CREATED", { messageId, intent: result.intent, reason: result.escalation_reason, confidence: result.confidence });
        }
        await prisma.message.create({ data: { id: crypto.randomUUID(), conversationId, direction: "OUTBOUND", content: result.answer, metadata: result } });
        await prisma.conversation.update({ where: { id: conversationId }, data: { lastMessageAt: new Date() } });
        await persistConversationMemory({ conversationId, customerId, inboundMessageId: messageId, result });
        persisted = true;
      }
    },
  }));
  return new Response(stream, { headers: { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache, no-transform", "x-conversation-id": conversationId, "server-timing": `preflight;dur=${(performance.now()-startedAt).toFixed(1)}` } });
}
