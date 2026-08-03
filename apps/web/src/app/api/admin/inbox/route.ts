import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { activeTicketStatuses } from "@/lib/handoff";
import { prisma } from "@/lib/prisma";

export async function GET(request: Request) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const query = new URL(request.url).searchParams;
  const status = query.get("status");
  const priority = query.get("priority");
  const assignment = query.get("assignment");
  const tickets = await prisma.ticket.findMany({
    where: {
      status: status ? status as never : { in: [...activeTicketStatuses] },
      conversationId: { not: { startsWith: "conv_history_" } },
      ...(priority ? { priority: priority as never } : {}),
      ...(assignment === "mine" ? { assignedTo: admin.id } : assignment === "unassigned" ? { assignedTo: null } : {}),
    },
    orderBy: [{ priority: "desc" }, { updatedAt: "asc" }],
    take: 100,
    include: { customer: { select: { name: true, email: true, tier: true } }, conversation: { select: { title: true, lastMessageAt: true, _count: { select: { messages: true } } } } },
  });
  return NextResponse.json({ tickets, adminId: admin.id });
}
