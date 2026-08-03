CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS "KnowledgeChunk_content_fts_idx" ON "KnowledgeChunk" USING GIN (to_tsvector('simple', content));
CREATE INDEX IF NOT EXISTS "KnowledgeVersion_title_fts_idx" ON "KnowledgeVersion" USING GIN (to_tsvector('simple', title));
CREATE INDEX IF NOT EXISTS "KnowledgeEntity_canonicalName_trgm_idx" ON "KnowledgeEntity" USING GIN ("canonicalName" gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "KnowledgeEntity_normalizedKey_trgm_idx" ON "KnowledgeEntity" USING GIN ("normalizedKey" gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "KnowledgeClaim_subject_trgm_idx" ON "KnowledgeClaim" USING GIN (subject gin_trgm_ops);
CREATE INDEX IF NOT EXISTS "KnowledgeClaim_value_trgm_idx" ON "KnowledgeClaim" USING GIN (value gin_trgm_ops);
