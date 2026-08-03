CREATE TABLE "KnowledgeIngestionRun" (
  "id" TEXT NOT NULL,
  "documentId" TEXT,
  "versionId" TEXT,
  "status" TEXT NOT NULL DEFAULT 'QUEUED',
  "stage" TEXT NOT NULL DEFAULT 'QUEUED',
  "progress" INTEGER NOT NULL DEFAULT 0,
  "processedUnits" INTEGER NOT NULL DEFAULT 0,
  "totalUnits" INTEGER NOT NULL DEFAULT 0,
  "model" TEXT NOT NULL DEFAULT 'cx/gpt-5.6-terra',
  "payload" JSONB NOT NULL DEFAULT '{}',
  "result" JSONB,
  "error" TEXT,
  "attempts" INTEGER NOT NULL DEFAULT 0,
  "heartbeatAt" TIMESTAMP(3),
  "startedAt" TIMESTAMP(3),
  "completedAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "KnowledgeIngestionRun_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "KnowledgeIngestionRun_status_createdAt_idx" ON "KnowledgeIngestionRun"("status", "createdAt");
CREATE INDEX "KnowledgeIngestionRun_documentId_createdAt_idx" ON "KnowledgeIngestionRun"("documentId", "createdAt");

CREATE TABLE "KnowledgeGraphSnapshot" (
  "id" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'BUILDING',
  "model" TEXT NOT NULL,
  "promptVersion" TEXT NOT NULL,
  "coverage" DOUBLE PRECISION NOT NULL DEFAULT 0,
  "documentCount" INTEGER NOT NULL DEFAULT 0,
  "chunkCount" INTEGER NOT NULL DEFAULT 0,
  "entityCount" INTEGER NOT NULL DEFAULT 0,
  "edgeCount" INTEGER NOT NULL DEFAULT 0,
  "claimCount" INTEGER NOT NULL DEFAULT 0,
  "communityCount" INTEGER NOT NULL DEFAULT 0,
  "summaryCount" INTEGER NOT NULL DEFAULT 0,
  "checksum" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT false,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "completedAt" TIMESTAMP(3),
  CONSTRAINT "KnowledgeGraphSnapshot_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "KnowledgeGraphSnapshot_active_createdAt_idx" ON "KnowledgeGraphSnapshot"("active", "createdAt");
CREATE INDEX "KnowledgeGraphSnapshot_status_createdAt_idx" ON "KnowledgeGraphSnapshot"("status", "createdAt");

CREATE TABLE "KnowledgeSummaryNode" (
  "id" TEXT NOT NULL,
  "snapshotId" TEXT NOT NULL,
  "versionId" TEXT,
  "parentId" TEXT,
  "level" INTEGER NOT NULL,
  "nodeType" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "summary" TEXT NOT NULL,
  "sourceChunkIds" JSONB NOT NULL DEFAULT '[]',
  "metadata" JSONB NOT NULL DEFAULT '{}',
  "embedding" vector(1536),
  "active" BOOLEAN NOT NULL DEFAULT false,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "KnowledgeSummaryNode_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "KnowledgeSummaryNode_snapshotId_level_active_idx" ON "KnowledgeSummaryNode"("snapshotId", "level", "active");
CREATE INDEX "KnowledgeSummaryNode_versionId_level_idx" ON "KnowledgeSummaryNode"("versionId", "level");
CREATE INDEX "KnowledgeSummaryNode_parentId_idx" ON "KnowledgeSummaryNode"("parentId");

CREATE TABLE "KnowledgeCommunity" (
  "id" TEXT NOT NULL,
  "snapshotId" TEXT NOT NULL,
  "parentId" TEXT,
  "level" INTEGER NOT NULL,
  "title" TEXT NOT NULL,
  "summary" TEXT NOT NULL,
  "fullContent" TEXT NOT NULL,
  "rank" DOUBLE PRECISION NOT NULL DEFAULT 0,
  "metadata" JSONB NOT NULL DEFAULT '{}',
  "embedding" vector(1536),
  "active" BOOLEAN NOT NULL DEFAULT false,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "KnowledgeCommunity_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "KnowledgeCommunity_snapshotId_level_active_idx" ON "KnowledgeCommunity"("snapshotId", "level", "active");
CREATE INDEX "KnowledgeCommunity_parentId_idx" ON "KnowledgeCommunity"("parentId");

CREATE TABLE "KnowledgeCommunityMember" (
  "id" TEXT NOT NULL,
  "communityId" TEXT NOT NULL,
  "entityId" TEXT,
  "chunkId" TEXT,
  "weight" DOUBLE PRECISION NOT NULL DEFAULT 1,
  "metadata" JSONB NOT NULL DEFAULT '{}',
  CONSTRAINT "KnowledgeCommunityMember_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "KnowledgeCommunityMember_communityId_idx" ON "KnowledgeCommunityMember"("communityId");
CREATE INDEX "KnowledgeCommunityMember_entityId_idx" ON "KnowledgeCommunityMember"("entityId");
CREATE INDEX "KnowledgeCommunityMember_chunkId_idx" ON "KnowledgeCommunityMember"("chunkId");
CREATE UNIQUE INDEX "KnowledgeCommunityMember_communityId_entityId_chunkId_key" ON "KnowledgeCommunityMember"("communityId", "entityId", "chunkId");
