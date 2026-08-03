import { NextResponse } from "next/server";

import { requireCustomer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const conversations = await prisma.conversation.findMany({
    where: { customerId: user.customerId, channel: "WEB", externalId: null },
    orderBy: { lastMessageAt: "desc" },
    take: 50,
    select: { id: true, title: true, createdAt: true, lastMessageAt: true, _count: { select: { messages: true } } },
  });
  return NextResponse.json({ conversations });
}

export async function POST() {
  const user = await requireCustomer();
  if (!user) return NextResponse.json({ error: "AUTHENTICATION_REQUIRED" }, { status: 401 });
  const conversation = await prisma.conversation.create({ data: { id: crypto.randomUUID(), customerId: user.customerId, channel: "WEB" } });
  return NextResponse.json({ conversation }, { status: 201 });
}
