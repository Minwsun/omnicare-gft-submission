import { NextResponse } from "next/server";
import { z } from "zod";

import { requireAdmin } from "@/lib/auth";
import { addTicketEvent } from "@/lib/handoff";
import { prisma } from "@/lib/prisma";

const schema = z.object({ content: z.string().trim().min(1).max(8000) });

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_MESSAGE" }, { status: 400 });
  const { id } = await params;
  const ticket = await prisma.ticket.findFirst({ where: { id, assignedTo: admin.id, status: { in: ["NEED_HUMAN", "PENDING_CUSTOMER", "PENDING_APPROVAL"] } } });
  if (!ticket) return NextResponse.json({ error: "CLAIM_REQUIRED" }, { status: 409 });
  const message = await prisma.message.create({ data: { conversationId: ticket.conversationId, direction: "OUTBOUND", content: parsed.data.content, metadata: { source: "HUMAN_ADMIN", adminId: admin.id, ticketId: ticket.id } } });
  await prisma.conversation.update({ where: { id: ticket.conversationId }, data: { lastMessageAt: new Date() } });
  await addTicketEvent(id, "ADMIN_REPLIED", { adminId: admin.id, messageId: message.id });
  return NextResponse.json({ message });
}
