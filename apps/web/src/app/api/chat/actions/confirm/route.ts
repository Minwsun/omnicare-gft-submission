import { NextResponse } from "next/server";
import { z } from "zod";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const schema = z.object({ confirmationToken: z.string().min(20).max(8000), conversationId: z.string().uuid() });

export async function POST(request: Request) {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_CONFIRMATION" }, { status: 400 });
  const conversation = await prisma.conversation.findFirst({ where: { id: parsed.data.conversationId, customerId: user.customerId } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (!serviceUrl) return NextResponse.json({ error: "AI_SERVICE_NOT_CONFIGURED" }, { status: 503 });
  const upstream = await fetch(`${serviceUrl}/agent/confirm`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ confirmation_token: parsed.data.confirmationToken, customer_id: user.customerId, conversation_id: conversation.id }), cache: "no-store" });
  const result = await upstream.json();
  if (!upstream.ok) return NextResponse.json({ error: result.detail || "CONFIRMATION_FAILED" }, { status: upstream.status });
  await prisma.message.create({ data: { conversationId: conversation.id, direction: "OUTBOUND", content: result.answer, metadata: result } });
  return NextResponse.json(result);
}
