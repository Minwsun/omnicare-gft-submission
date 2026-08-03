import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function GET(_: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!await requireAdmin()) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const run = await prisma.knowledgeIngestionRun.findUnique({ where: { id } });
  if (!run) return NextResponse.json({ error: "RUN_NOT_FOUND" }, { status: 404 });
  const queuedForSeconds = ["QUEUED", "RETRY"].includes(run.status) ? Math.max(0, Math.floor((Date.now() - run.createdAt.getTime()) / 1000)) : 0;
  return NextResponse.json({ ...run, queuedForSeconds, stale: queuedForSeconds >= 15 });
}
