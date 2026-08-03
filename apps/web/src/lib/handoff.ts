import { Prisma } from "@prisma/client";

import { prisma } from "@/lib/prisma";

export const activeTicketStatuses = ["OPEN", "NEED_HUMAN", "PENDING_CUSTOMER", "PENDING_APPROVAL"] as const;

export async function findActiveTicket(conversationId: string) {
  return prisma.ticket.findFirst({
    where: { conversationId, status: { in: [...activeTicketStatuses] } },
    orderBy: { updatedAt: "desc" },
  });
}

export async function addTicketEvent(ticketId: string, type: string, payload?: Prisma.InputJsonValue) {
  return prisma.ticketEvent.create({ data: { ticketId, type, ...(payload === undefined ? {} : { payload }) } });
}

export function publicHandoffState(ticket: { id: string; status: string; priority: string; assignedTo: string | null; category: string; updatedAt: Date } | null) {
  if (!ticket) return null;
  return {
    ticketId: ticket.id,
    status: ticket.status,
    priority: ticket.priority,
    category: ticket.category,
    assigned: Boolean(ticket.assignedTo),
    mode: ticket.status === "PENDING_CUSTOMER" ? "WAITING_CUSTOMER" : ticket.assignedTo ? "HUMAN_ACTIVE" : "WAITING_HUMAN",
    updatedAt: ticket.updatedAt,
  };
}
