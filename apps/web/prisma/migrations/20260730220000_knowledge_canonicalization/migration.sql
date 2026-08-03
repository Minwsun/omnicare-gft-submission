CREATE TYPE "KnowledgeMarketplace" AS ENUM ('SHOPEE', 'TIKTOK_SHOP', 'INTERNAL');

ALTER TABLE "KnowledgeDocument"
ADD COLUMN "marketplace" "KnowledgeMarketplace" NOT NULL DEFAULT 'INTERNAL';

ALTER TABLE "KnowledgeChunk"
ADD COLUMN "contentHash" TEXT,
ADD COLUMN "canonicalChunkId" TEXT,
ADD COLUMN "retrievalEnabled" BOOLEAN NOT NULL DEFAULT true;

WITH classified AS (
  SELECT
    d.id,
    CASE
      WHEN lower(COALESCE(s."baseUrl", sp.url, '')) LIKE '%shopee.%'
        OR lower(COALESCE(s."baseUrl", sp.url, '')) LIKE '%help.shopee%'
        OR lower(COALESCE(s."baseUrl", sp.url, '')) LIKE '%banhang.shopee%'
        THEN 'SHOPEE'::"KnowledgeMarketplace"
      WHEN lower(COALESCE(s."baseUrl", sp.url, '')) LIKE '%tiktok%'
        OR lower(COALESCE(v.title, '')) LIKE '%tiktok%'
        THEN 'TIKTOK_SHOP'::"KnowledgeMarketplace"
      ELSE 'INTERNAL'::"KnowledgeMarketplace"
    END AS marketplace
  FROM "KnowledgeDocument" d
  LEFT JOIN "KnowledgeVersion" v ON v.id = d."currentVersionId"
  LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId" = d.id
  LEFT JOIN "KnowledgeSourceSnapshot" ss ON ss.id = sp."snapshotId"
  LEFT JOIN "KnowledgeSource" s ON s.id = ss."sourceId"
)
UPDATE "KnowledgeDocument" d
SET marketplace = classified.marketplace
FROM classified
WHERE classified.id = d.id;

UPDATE "KnowledgeChunk"
SET "contentHash" = md5(
  regexp_replace(
    lower(trim(regexp_replace(content, '\s+', ' ', 'g'))),
    '[[:punct:]]+',
    '',
    'g'
  )
);

WITH ranked AS (
  SELECT
    c.id,
    first_value(c.id) OVER (
      PARTITION BY c."contentHash"
      ORDER BY
        CASE d.marketplace WHEN 'SHOPEE' THEN 0 WHEN 'INTERNAL' THEN 1 ELSE 2 END,
        CASE WHEN d."currentVersionId" = v.id AND v.status = 'PUBLISHED' AND v.searchable THEN 0 ELSE 1 END,
        d."authorityLevel" DESC,
        v."effectiveFrom" DESC,
        CASE WHEN sp.url ~* '^https?://' THEN 0 ELSE 1 END,
        c.id
    ) AS canonical_id,
    row_number() OVER (
      PARTITION BY c."contentHash"
      ORDER BY
        CASE d.marketplace WHEN 'SHOPEE' THEN 0 WHEN 'INTERNAL' THEN 1 ELSE 2 END,
        CASE WHEN d."currentVersionId" = v.id AND v.status = 'PUBLISHED' AND v.searchable THEN 0 ELSE 1 END,
        d."authorityLevel" DESC,
        v."effectiveFrom" DESC,
        CASE WHEN sp.url ~* '^https?://' THEN 0 ELSE 1 END,
        c.id
    ) AS duplicate_rank
  FROM "KnowledgeChunk" c
  JOIN "KnowledgeVersion" v ON v.id = c."versionId"
  JOIN "KnowledgeDocument" d ON d.id = v."documentId"
  LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId" = d.id
  WHERE c."contentHash" IS NOT NULL
)
UPDATE "KnowledgeChunk" c
SET
  "canonicalChunkId" = CASE WHEN ranked.duplicate_rank = 1 THEN NULL ELSE ranked.canonical_id END,
  "retrievalEnabled" = ranked.duplicate_rank = 1
FROM ranked
WHERE ranked.id = c.id;

ALTER TABLE "KnowledgeChunk"
ADD CONSTRAINT "KnowledgeChunk_canonicalChunkId_fkey"
FOREIGN KEY ("canonicalChunkId") REFERENCES "KnowledgeChunk"(id)
ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX "KnowledgeDocument_marketplace_visibility_idx"
ON "KnowledgeDocument"("marketplace", "visibility");

CREATE INDEX "KnowledgeChunk_contentHash_retrievalEnabled_idx"
ON "KnowledgeChunk"("contentHash", "retrievalEnabled");

CREATE INDEX "KnowledgeChunk_canonicalChunkId_idx"
ON "KnowledgeChunk"("canonicalChunkId");
