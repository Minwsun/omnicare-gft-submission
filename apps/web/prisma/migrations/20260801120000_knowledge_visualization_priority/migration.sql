ALTER TABLE "KnowledgeIngestionRun" ADD COLUMN "priority" TEXT NOT NULL DEFAULT 'NORMAL';
DROP INDEX IF EXISTS "KnowledgeIngestionRun_status_createdAt_idx";
CREATE INDEX "KnowledgeIngestionRun_status_priority_createdAt_idx" ON "KnowledgeIngestionRun"("status", "priority", "createdAt");

CREATE TABLE "KnowledgeVisualizationRevision" (
  "id" TEXT NOT NULL,
  "documentId" TEXT NOT NULL,
  "versionId" TEXT,
  "ingestionRunId" TEXT,
  "revision" INTEGER NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'BUILDING',
  "model" TEXT NOT NULL,
  "promptVersion" TEXT NOT NULL,
  "sourceHash" TEXT NOT NULL,
  "nodes" JSONB NOT NULL DEFAULT '[]',
  "edges" JSONB NOT NULL DEFAULT '[]',
  "placement" JSONB NOT NULL DEFAULT '{}',
  "validation" JSONB NOT NULL DEFAULT '{}',
  "active" BOOLEAN NOT NULL DEFAULT false,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "completedAt" TIMESTAMP(3),
  CONSTRAINT "KnowledgeVisualizationRevision_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "KnowledgeVisualizationRevision_documentId_revision_key" ON "KnowledgeVisualizationRevision"("documentId", "revision");
CREATE INDEX "KnowledgeVisualizationRevision_documentId_active_createdAt_idx" ON "KnowledgeVisualizationRevision"("documentId", "active", "createdAt");
CREATE INDEX "KnowledgeVisualizationRevision_versionId_idx" ON "KnowledgeVisualizationRevision"("versionId");
CREATE INDEX "KnowledgeVisualizationRevision_ingestionRunId_idx" ON "KnowledgeVisualizationRevision"("ingestionRunId");
