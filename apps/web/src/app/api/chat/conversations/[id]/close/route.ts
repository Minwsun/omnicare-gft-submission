import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await requireCustomer();
  if (!user?.customerId) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const { id } = await params;
  const conversation = await prisma.conversation.findFirst({ where: { id, customerId: user.customerId, channel: "WEB" }, select: { id: true } });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  const now = new Date();
  await prisma.$transaction([
    prisma.conversation.update({ where: { id }, data: { closedAt: now } }),
    prisma.chatAttachment.updateMany({ where: { conversationId: id, bytes: { not: null } }, data: { bytes: null, deletedAt: now, status: "PURGED" } }),
  ]);
  return NextResponse.json({ closed: true });
}
