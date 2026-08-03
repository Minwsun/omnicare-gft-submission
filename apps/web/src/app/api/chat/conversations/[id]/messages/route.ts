import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const { id } = await params;
  const conversation = await prisma.conversation.findFirst({
    where: { id, customerId: user.customerId, channel: "WEB" },
    include: { messages: { orderBy: { createdAt: "asc" }, include: { attachments: { select: { id: true, fileName: true, mimeType: true, size: true, status: true, analysis: true } } } } },
  });
  if (!conversation) return NextResponse.json({ error: "CONVERSATION_NOT_FOUND" }, { status: 404 });
  return NextResponse.json({ conversation });
}
