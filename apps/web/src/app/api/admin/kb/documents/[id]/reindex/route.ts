import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export async function POST(_: Request, { params }: { params: Promise<{ id: string }> }) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const { id } = await params;
  const document = await prisma.knowledgeDocument.findUnique({ where: { id }, select: { id: true, archivedAt: true, currentVersionId: true } });
  if (!document) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  if (document.archivedAt || !document.currentVersionId) return NextResponse.json({ error: "ACTIVE_DOCUMENT_REQUIRED" }, { status: 409 });
  const active = await prisma.knowledgeIngestionRun.findFirst({ where: { status: { in: ["QUEUED", "RUNNING", "RETRY"] }, payload: { path: ["mode"], equals: "REBUILD_ALL" } } });
  if (active) return NextResponse.json({ runId: active.id, status: active.status, reused: true }, { status: 202 });
  const run = await prisma.knowledgeIngestionRun.create({ data: { id: `kbir_${randomUUID()}`, documentId: id, versionId: document.currentVersionId, model: process.env.LLM_REASONING_MODEL || "cx/gpt-5.6-terra", payload: { mode: "REBUILD_ALL", requestedDocumentId: id, actorId: admin.id } } });
  return NextResponse.json({ runId: run.id, status: run.status }, { status: 202 });
}
