import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const ticket = await prisma.ticket.findUnique({
    where: { id },
    include: {
      customer: true,
      order: { include: { items: true, shipments: true, payments: true, refunds: true } },
      events: { orderBy: { createdAt: "asc" } },
      conversation: {
        include: {
          messages: { orderBy: { createdAt: "asc" }, include: { attachments: { select: { id: true, fileName: true, mimeType: true, size: true, status: true, analysis: true } } } },
          aiRuns: { orderBy: { startedAt: "desc" }, take: 5, include: { steps: true, toolCalls: true, retrievals: true } },
        },
      },
    },
  });
  if (!ticket) return NextResponse.json({ error: "TICKET_NOT_FOUND" }, { status: 404 });
  return NextResponse.json({ ticket });
}
