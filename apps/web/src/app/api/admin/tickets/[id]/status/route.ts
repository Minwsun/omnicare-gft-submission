import { NextResponse } from "next/server";
import { z } from "zod";

import { requireAdmin } from "@/lib/auth";
import { addTicketEvent } from "@/lib/handoff";
import { prisma } from "@/lib/prisma";

const schema = z.object({ action: z.enum(["WAIT_CUSTOMER", "RESOLVE", "CLOSE", "RELEASE_AI"]) });

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const parsed = schema.safeParse(await request.json());
  if (!parsed.success) return NextResponse.json({ error: "INVALID_ACTION" }, { status: 400 });
  const { id } = await params;
  const ticket = await prisma.ticket.findFirst({ where: { id, assignedTo: admin.id } });
  if (!ticket) return NextResponse.json({ error: "CLAIM_REQUIRED" }, { status: 409 });
  const state = {
    WAIT_CUSTOMER: { status: "PENDING_CUSTOMER" as const, assignedTo: admin.id, event: "WAITING_CUSTOMER" },
    RESOLVE: { status: "RESOLVED" as const, assignedTo: admin.id, event: "RESOLVED" },
    CLOSE: { status: "CLOSED" as const, assignedTo: admin.id, event: "CLOSED" },
    RELEASE_AI: { status: "RESOLVED" as const, assignedTo: null, event: "RELEASED_TO_AI" },
  }[parsed.data.action];
  if (ticket.status === state.status && ticket.assignedTo === state.assignedTo) {
    return NextResponse.json({ ticket });
  }
  const updated = await prisma.ticket.update({ where: { id }, data: { status: state.status, assignedTo: state.assignedTo } });
  await addTicketEvent(id, state.event, { adminId: admin.id });
  return NextResponse.json({ ticket: updated });
}
