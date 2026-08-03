import { createHash, randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { z } from "zod";

import { requireAdmin } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const schema = z.object({
  documentId: z.string().trim().min(1).optional(),
  title: z.string().trim().min(1).max(180),
  content: z.string().trim().min(20).max(500000),
  kind: z.enum(["DOCUMENT","FAQ","POLICY","TERMS","GUIDE","PRODUCT_GUIDE","TROUBLESHOOTING","SOP","INCIDENT","HISTORICAL_RESOLUTION"]).default("DOCUMENT"),
  importance: z.enum(["LOW","MEDIUM","HIGH","CRITICAL"]).default("MEDIUM"),
  visibility: z.enum(["PUBLIC","CUSTOMER_AUTHENTICATED","INTERNAL"]).default("PUBLIC"),
  marketplace: z.enum(["SHOPEE","TIKTOK_SHOP","INTERNAL"]).default("SHOPEE"),
  mandatory: z.boolean().default(false),
  autoPublish: z.boolean().default(true),
  priority: z.enum(["HIGH", "NORMAL", "LOW"]).default("NORMAL"),
});

const normalize = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("vi-VN").replace(/\s+/g, " ").trim();
const contentHash = (value: string) => createHash("sha256").update(normalize(value)).digest("hex");

export async function POST(request: Request) {
  const admin = await requireAdmin();
  if (!admin) return NextResponse.json({ error: "FORBIDDEN" }, { status: 403 });
  const input = schema.safeParse(await request.json());
  if (!input.success) return NextResponse.json({ error: "INVALID_INGESTION", details: input.error.flatten() }, { status: 400 });

  const sourceHash = contentHash(input.data.content);
  const exactDuplicate = await prisma.knowledgeChunk.findFirst({
    where: { contentHash: sourceHash, retrievalEnabled: true, version: { searchable: true, status: "PUBLISHED", document: { archivedAt: null } } },
    include: { version: true },
  });
  if (exactDuplicate) return NextResponse.json({ status: "DUPLICATE", documentId: exactDuplicate.version.documentId, versionId: exactDuplicate.versionId, chunkId: exactDuplicate.id });

  const requestedDocument = input.data.documentId ? await prisma.knowledgeDocument.findUnique({ where: { id: input.data.documentId } }) : null;
  if (input.data.documentId && !requestedDocument) return NextResponse.json({ error: "DOCUMENT_NOT_FOUND" }, { status: 404 });
  const titleCandidates = requestedDocument ? [] : await prisma.knowledgeDocument.findMany({ where: { archivedAt: null }, include: { currentVersion: true } });
  const canonical = requestedDocument ?? titleCandidates.find((document) => document.currentVersion && normalize(document.currentVersion.title) === normalize(input.data.title));
  const run = await prisma.knowledgeIngestionRun.create({
    data: {
      id: `kbir_${randomUUID()}`,
      documentId: canonical?.id,
      model: process.env.EMBEDDING_MODEL || "hybrid-rag-full-text",
      priority: input.data.priority,
      payload: { ...input.data, documentId: canonical?.id, actorId: admin.id, sourceHash } as Prisma.InputJsonValue,
    },
  });
  const serviceUrl = process.env.AI_SERVICE_URL;
  if (serviceUrl) {
    try {
      await fetch(`${serviceUrl}/retrieval/ingestion/wake`, { method: "POST", cache: "no-store", signal: AbortSignal.timeout(1500) });
    } catch {
      // Polling fallback handles Render cold starts and temporary network failures.
    }
  }
  return NextResponse.json({ runId: run.id, documentId: canonical?.id, status: run.status, stage: run.stage }, { status: 202 });
}
