import { NextResponse } from "next/server";

import { getSessionUser, revokeSession } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST() {
  const user = await getSessionUser();
  await revokeSession();
  if (user) await prisma.auditLog.create({ data: { actorId: user.id, actorRole: user.role, action: "LOGOUT", entityType: "UserAccount", entityId: user.id } });
  return NextResponse.json({ ok: true });
}
