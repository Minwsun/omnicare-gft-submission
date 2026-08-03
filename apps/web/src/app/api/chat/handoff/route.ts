import { NextResponse } from "next/server";
import { z } from "zod";

import { requireCustomer } from "@/lib/auth";
import { addTicketEvent, findActiveTicket, publicHandoffState } from "@/lib/handoff";
import { prisma } from "@/lib/prisma";

const schema = z.object({ conversationId: z.string().uuid(), reason: z.string().trim().max(500).default("Khách hàng yêu cầu gặp nhân viên") });

export async function POST(request: Request) {
  const user = await requireCustomer();
  if (!user?.customerId) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_REQUEST" }, { status: 400 });
  const conversation = await prisma.conversation.findFirst({ where: { id: parsed.data.conversationId, customerId: user.customerId, channel: "WEB" } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  let ticket = await findActiveTicket(conversation.id);
  if (!ticket) {
    ticket = await prisma.ticket.create({
      data: {
        id: `TCK-${crypto.randomUUID().slice(0, 12).toUpperCase()}`,
        customerId: user.customerId,
        conversationId: conversation.id,
        status: "NEED_HUMAN",
        priority: "MEDIUM",
        category: "CUSTOMER_REQUEST",
        summary: parsed.data.reason,
      },
    });
  }
  await addTicketEvent(ticket.id, "CUSTOMER_REQUESTED", { reason: parsed.data.reason });
  return NextResponse.json({ handoff: publicHandoffState(ticket) });
}

export async function GET(request: Request) {
  const user = await requireCustomer();
  if (!user?.customerId) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const conversationId = new URL(request.url).searchParams.get("conversationId");
  if (!conversationId) return NextResponse.json({ error: "CONVERSATION_REQUIRED" }, { status: 400 });
  const conversation = await prisma.conversation.findFirst({ where: { id: conversationId, customerId: user.customerId, channel: "WEB" } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  return NextResponse.json({ handoff: publicHandoffState(await findActiveTicket(conversationId)) });
}

export async function DELETE(request: Request) {
  const user = await requireCustomer();
  if (!user?.customerId) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const conversationId = new URL(request.url).searchParams.get("conversationId");
  if (!conversationId) return NextResponse.json({ error: "CONVERSATION_REQUIRED" }, { status: 400 });
  const ticket = await findActiveTicket(conversationId);
  if (!ticket || ticket.customerId !== user.customerId) return NextResponse.json({ error: "TICKET_NOT_FOUND" }, { status: 404 });
  if (ticket.assignedTo) return NextResponse.json({ error: "HUMAN_ALREADY_JOINED" }, { status: 409 });
  const closed = await prisma.ticket.update({ where: { id: ticket.id }, data: { status: "CLOSED" } });
  await addTicketEvent(ticket.id, "CUSTOMER_CANCELLED");
  return NextResponse.json({ handoff: publicHandoffState(closed) });
}
