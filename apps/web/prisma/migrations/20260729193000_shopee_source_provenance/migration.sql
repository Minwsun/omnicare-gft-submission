CREATE TABLE "KnowledgeSource" (
  "id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "baseUrl" TEXT NOT NULL,
  "locale" TEXT NOT NULL DEFAULT 'vi-VN',
  "authority" INTEGER NOT NULL DEFAULT 100,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "KnowledgeSource_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "KnowledgeSourceSnapshot" (
  "id" TEXT NOT NULL,
  "sourceId" TEXT NOT NULL,
  "capturedAt" TIMESTAMP(3) NOT NULL,
  "sitemapUrl" TEXT NOT NULL,
  "checksum" TEXT NOT NULL,
  "pageCount" INTEGER NOT NULL DEFAULT 0,
  "status" TEXT NOT NULL DEFAULT 'RUNNING',
  "error" TEXT,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "KnowledgeSourceSnapshot_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "KnowledgeSourcePage" (
  "id" TEXT NOT NULL,
  "snapshotId" TEXT NOT NULL,
  "url" TEXT NOT NULL,
  "title" TEXT NOT NULL,
  "rawHtml" TEXT NOT NULL,
  "normalizedText" TEXT NOT NULL,
  "checksum" TEXT NOT NULL,
  "fetchedAt" TIMESTAMP(3) NOT NULL,
  "knowledgeDocumentId" TEXT,
  CONSTRAINT "KnowledgeSourcePage_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "KnowledgeSourceSection" (
  "id" TEXT NOT NULL,
  "sourcePageId" TEXT NOT NULL,
  "heading" TEXT NOT NULL,
  "content" TEXT NOT NULL,
  "ordinal" INTEGER NOT NULL,
  "checksum" TEXT NOT NULL,
  "versionId" TEXT NOT NULL,
  "chunkId" TEXT NOT NULL,
  CONSTRAINT "KnowledgeSourceSection_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "KnowledgeSource_baseUrl_locale_key" ON "KnowledgeSource"("baseUrl", "locale");
CREATE UNIQUE INDEX "KnowledgeSourceSnapshot_sourceId_checksum_key" ON "KnowledgeSourceSnapshot"("sourceId", "checksum");
CREATE INDEX "KnowledgeSourceSnapshot_sourceId_capturedAt_idx" ON "KnowledgeSourceSnapshot"("sourceId", "capturedAt");
CREATE UNIQUE INDEX "KnowledgeSourcePage_knowledgeDocumentId_key" ON "KnowledgeSourcePage"("knowledgeDocumentId");
CREATE UNIQUE INDEX "KnowledgeSourcePage_snapshotId_url_key" ON "KnowledgeSourcePage"("snapshotId", "url");
CREATE INDEX "KnowledgeSourcePage_url_idx" ON "KnowledgeSourcePage"("url");
CREATE INDEX "KnowledgeSourcePage_checksum_idx" ON "KnowledgeSourcePage"("checksum");
CREATE UNIQUE INDEX "KnowledgeSourceSection_chunkId_key" ON "KnowledgeSourceSection"("chunkId");
CREATE UNIQUE INDEX "KnowledgeSourceSection_sourcePageId_ordinal_key" ON "KnowledgeSourceSection"("sourcePageId", "ordinal");
CREATE INDEX "KnowledgeSourceSection_versionId_idx" ON "KnowledgeSourceSection"("versionId");

ALTER TABLE "KnowledgeSourceSnapshot" ADD CONSTRAINT "KnowledgeSourceSnapshot_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "KnowledgeSource"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "KnowledgeSourcePage" ADD CONSTRAINT "KnowledgeSourcePage_snapshotId_fkey" FOREIGN KEY ("snapshotId") REFERENCES "KnowledgeSourceSnapshot"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "KnowledgeSourcePage" ADD CONSTRAINT "KnowledgeSourcePage_knowledgeDocumentId_fkey" FOREIGN KEY ("knowledgeDocumentId") REFERENCES "KnowledgeDocument"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "KnowledgeSourceSection" ADD CONSTRAINT "KnowledgeSourceSection_sourcePageId_fkey" FOREIGN KEY ("sourcePageId") REFERENCES "KnowledgeSourcePage"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "KnowledgeSourceSection" ADD CONSTRAINT "KnowledgeSourceSection_versionId_fkey" FOREIGN KEY ("versionId") REFERENCES "KnowledgeVersion"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "KnowledgeSourceSection" ADD CONSTRAINT "KnowledgeSourceSection_chunkId_fkey" FOREIGN KEY ("chunkId") REFERENCES "KnowledgeChunk"("id") ON DELETE CASCADE ON UPDATE CASCADE;
