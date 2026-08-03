import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST() {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const active = await prisma.knowledgeIngestionRun.findFirst({ where: { status: { in: ["QUEUED", "RUNNING", "RETRY"] }, payload: { path: ["mode"], equals: "REBUILD_ALL" } } });
  if (active) return NextResponse.json({ runId: active.id, status: active.status }, { status: 202 });
  const run = await prisma.knowledgeIngestionRun.create({ data: { id: `kbir_${randomUUID()}`, model: process.env.LLM_REASONING_MODEL || "cx/gpt-5.6-terra", payload: { mode: "REBUILD_ALL", actorId: admin.id } } });
  return NextResponse.json({ runId: run.id, status: run.status }, { status: 202 });
}
