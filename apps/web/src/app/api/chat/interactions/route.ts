import { NextResponse } from "next/server";
import { z } from "zod";

import { requireCustomer } from "@/lib/auth";
import { persistConversationMemory } from "@/lib/conversation-memory";
import { prisma } from "@/lib/prisma";

const schema = z.object({
  interactionId: z.string().min(1).max(200),
  conversationId: z.string().uuid(),
  action: z.enum(["SELECT", "SUBMIT", "CONFIRM", "REJECT", "CANCEL"]),
  values: z.record(z.string(), z.unknown()).default({}),
  displayText: z.string().trim().min(1).max(1000),
  continuationToken: z.string().min(20).max(12000),
});

export async function POST(request: Request) {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_INTERACTION" }, { status: 400 });
  const conversation = await prisma.conversation.findFirst({ where: { id: parsed.data.conversationId, customerId: user.customerId } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });
  const inboundMessageId = crypto.randomUUID();
  await prisma.message.create({
    data: {
      id: inboundMessageId,
      conversationId: conversation.id,
      direction: "INBOUND",
      content: parsed.data.displayText,
      metadata: { interactionId: parsed.data.interactionId, action: parsed.data.action },
    },
  });
  await prisma.conversation.update({ where: { id: conversation.id }, data: { lastMessageAt: new Date() } });
  const upstream = await fetch(`${serviceUrl}/agent/interactions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ interaction_id: parsed.data.interactionId, conversation_id: conversation.id, customer_id: user.customerId, action: parsed.data.action, values: parsed.data.values, continuation_token: parsed.data.continuationToken }),
    cache: "no-store",
  });
  const result = await upstream.json();
  if (!upstream.ok) {
    const answer = "Mình chưa thể xử lý lựa chọn này. Bạn thử lại hoặc gửi yêu cầu mới nhé.";
    await prisma.message.create({ data: { conversationId: conversation.id, direction: "OUTBOUND", content: answer, metadata: { error: result.detail || "INTERACTION_FAILED" } } });
    return NextResponse.json({ error: result.detail || "INTERACTION_FAILED", answer }, { status: upstream.status });
  }
  await prisma.message.create({ data: { conversationId: conversation.id, direction: "OUTBOUND", content: result.answer, metadata: result } });
  await prisma.conversation.update({ where: { id: conversation.id }, data: { lastMessageAt: new Date() } });
  await persistConversationMemory({ conversationId: conversation.id, customerId: user.customerId!, inboundMessageId, result });
  return NextResponse.json(result);
}
