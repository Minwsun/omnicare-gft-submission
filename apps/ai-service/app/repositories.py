import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import asyncpg

from .config import settings


class Repository:
    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def customer_profile(self, customer_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('SELECT id, name, "phoneMasked", tier, locale, "createdAt" FROM "Customer" WHERE id = $1', customer_id)
        return dict(row) if row else None

    async def recent_orders(self, customer_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('SELECT id, status, "totalAmount", currency, "placedAt", "updatedAt" FROM "Order" WHERE "customerId" = $1 ORDER BY "placedAt" DESC LIMIT $2', customer_id, limit)
        return [dict(row) for row in rows]

    async def order_summary(self, customer_id: str) -> Dict[str, Any]:
        await self.connect()
        rows = await self.pool.fetch('SELECT status::text AS status, count(*)::int AS count FROM "Order" WHERE "customerId" = $1 GROUP BY status ORDER BY status', customer_id)
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        return {"total": sum(counts.values()), "byStatus": counts}

    async def orders_by_status(self, customer_id: str, statuses: List[str], limit: int = 8) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('SELECT id, status, "totalAmount", currency, "placedAt", "updatedAt" FROM "Order" WHERE "customerId" = $1 AND status::text = ANY($2::text[]) ORDER BY "placedAt" DESC LIMIT $3', customer_id, statuses, limit)
        return [dict(row) for row in rows]

    async def order_details(self, customer_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('SELECT id, status, "totalAmount", currency, "placedAt", "updatedAt" FROM "Order" WHERE id = $1 AND "customerId" = $2', order_id, customer_id)
        return dict(row) if row else None

    async def shipment_status(self, customer_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow(r'''
            SELECT o.id AS "orderId", s.id, s.carrier, s."trackingMasked", s.status,
                   s."estimatedDelivery", s."observedAt"
            FROM "Order" o
            LEFT JOIN LATERAL (
              SELECT id, carrier, "trackingMasked", status, "estimatedDelivery", "observedAt"
              FROM "Shipment"
              WHERE "orderId" = o.id
              ORDER BY "observedAt" DESC
              LIMIT 1
            ) s ON true
            WHERE o.id = $1 AND o."customerId" = $2
        ''', order_id, customer_id)
        return dict(row) if row else None

    async def payment_status(self, customer_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('SELECT p.id, p.provider, p.status, p.amount, p.currency, p."maskedReference", p."observedAt" FROM "Payment" p JOIN "Order" o ON o.id = p."orderId" WHERE p."orderId" = $1 AND o."customerId" = $2 ORDER BY p."observedAt" DESC LIMIT 1', order_id, customer_id)
        return dict(row) if row else None

    async def refund_status(self, customer_id: str, order_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('SELECT r.id, r.status, r.amount, r.reason, r."observedAt", r."referenceId" FROM "Refund" r JOIN "Order" o ON o.id = r."orderId" WHERE r."orderId" = $1 AND o."customerId" = $2 ORDER BY r."observedAt" DESC LIMIT 1', order_id, customer_id)
        return dict(row) if row else None

    async def return_context(self, customer_id: str, order_id: str) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch(r'''
            SELECT o.id AS "orderId", o.status::text AS "orderStatus", oi.id AS "orderItemId", oi.quantity,
                   p.id AS "productId", p.sku, p.name AS "productName", p.category,
                   prp.returnable AS "profileReturnable", prp."sealedRequired", prp."accessoriesRequired",
                   prp."evidenceTypes" AS "profileEvidenceTypes", prp.exclusions,
                   delivered."occurredAt" AS "deliveredAt"
            FROM "Order" o
            JOIN "OrderItem" oi ON oi."orderId" = o.id
            JOIN "Product" p ON p.id = oi."productId"
            LEFT JOIN "ProductReturnProfile" prp ON prp."productId" = p.id
            LEFT JOIN LATERAL (
              SELECT se."occurredAt" FROM "ShipmentEvent" se
              JOIN "Shipment" s ON s.id = se."shipmentId"
              WHERE s."orderId" = o.id AND se.status = 'DELIVERED'
              ORDER BY se."occurredAt" DESC LIMIT 1
            ) delivered ON true
            WHERE o.id = $1 AND o."customerId" = $2
            ORDER BY oi.id
        ''', order_id, customer_id)
        return [dict(row) for row in rows]

    async def return_rule(self, category: str, reason_code: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('''
            SELECT id, category, "reasonCode", "windowDays", returnable, "sealedRequired", "evidenceTypes",
                   conditions, exceptions, "authorityLevel", "effectiveFrom", "effectiveTo", "documentId", "versionId"
            FROM "ReturnPolicyRule"
            WHERE category = $1 AND "reasonCode" = $2 AND "effectiveFrom" <= now()
              AND ("effectiveTo" IS NULL OR "effectiveTo" > now())
            ORDER BY "authorityLevel" DESC LIMIT 1
        ''', category, reason_code)
        return dict(row) if row else None

    async def knowledge_citation(self, document_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('''
            SELECT d.id AS "documentId", d.slug, v.title, v."semanticVersion", v."effectiveFrom", sp.url AS "publicUrl"
            FROM "KnowledgeDocument" d
            JOIN "KnowledgeVersion" v ON v.id = $2 AND v."documentId" = d.id
            LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId" = d.id
            WHERE d.id = $1 AND d.visibility = 'PUBLIC' AND v.status = 'PUBLISHED'
            LIMIT 1
        ''', document_id, version_id)
        return dict(row) if row else None

    async def search_knowledge(self, query: str, locale: str, limit: int, visibility: str = "PUBLIC") -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch(r'''
            SELECT d.id AS document_id, v.id AS version_id, c.id AS chunk_id, d.type::text AS document_type, v.title, c.section,
                   c.content, v."semanticVersion" AS semantic_version, d."authorityLevel" AS authority_level,
                   v."effectiveFrom" AS effective_from, left(v.summary, 700) AS parent_summary,
                   ts_rank_cd(to_tsvector('simple', v.title), plainto_tsquery('simple', $1)) + ts_rank_cd(to_tsvector('simple', c.content), plainto_tsquery('simple', $1)) AS score,
                   COALESCE(sp.url, '/help/' || d.slug) AS public_url
            FROM "KnowledgeChunk" c
            JOIN "KnowledgeVersion" v ON v.id = c."versionId"
            JOIN "KnowledgeDocument" d ON d.id = v."documentId"
            LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId" = d.id
            WHERE d.locale = $2 AND (d.visibility = 'PUBLIC' OR ($4 = 'CUSTOMER_AUTHENTICATED' AND d.visibility = 'CUSTOMER_AUTHENTICATED')) AND v.status = 'PUBLISHED'
              AND d."archivedAt" IS NULL AND c."retrievalEnabled" = true
              AND v.searchable = true AND v."effectiveFrom" <= now()
              AND (v."effectiveTo" IS NULL OR v."effectiveTo" > now())
              AND (to_tsvector('simple', v.title) @@ plainto_tsquery('simple', $1) OR to_tsvector('simple', c.content) @@ plainto_tsquery('simple', $1))
            ORDER BY score DESC, d."authorityLevel" DESC
            LIMIT $3
        ''', query, locale, limit, visibility)
        return [dict(row) for row in rows]

    async def search_knowledge_vector(self, embedding: str, locale: str, limit: int, visibility: str = "PUBLIC") -> List[Dict[str, Any]]:
        if not embedding:
            return []
        await self.connect()
        rows = await self.pool.fetch(r'''
            SELECT d.id AS document_id, v.id AS version_id, c.id AS chunk_id, d.type::text AS document_type, v.title, c.section,
                   c.content, v."semanticVersion" AS semantic_version, d."authorityLevel" AS authority_level,
                   v."effectiveFrom" AS effective_from, left(v.summary,700) AS parent_summary,
                   (1 - (c.embedding <=> $1::vector))::float AS score,
                   COALESCE(sp.url, '/help/' || d.slug) AS public_url
            FROM "KnowledgeChunk" c JOIN "KnowledgeVersion" v ON v.id=c."versionId" JOIN "KnowledgeDocument" d ON d.id=v."documentId"
            LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId"=d.id
            WHERE c.embedding IS NOT NULL AND d.locale=$2
              AND (d.visibility='PUBLIC' OR ($4='CUSTOMER_AUTHENTICATED' AND d.visibility='CUSTOMER_AUTHENTICATED'))
              AND d."archivedAt" IS NULL AND v.status='PUBLISHED' AND c."retrievalEnabled"=true AND v.searchable=true
              AND v."effectiveFrom"<=now() AND (v."effectiveTo" IS NULL OR v."effectiveTo">now())
            ORDER BY c.embedding <=> $1::vector, d."authorityLevel" DESC LIMIT $3
        ''', embedding, locale, limit, visibility)
        return [dict(row) for row in rows]

    async def search_summary_branches(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('''
            SELECT id,title,summary,"sourceChunkIds",level,"nodeType",
                   ts_rank_cd(to_tsvector('simple', unaccent(lower(title || ' ' || summary))), plainto_tsquery('simple', unaccent(lower($1))))::float AS score
            FROM "KnowledgeSummaryNode"
            WHERE active=true AND level >= 2
              AND to_tsvector('simple', unaccent(lower(title || ' ' || summary))) @@ plainto_tsquery('simple', unaccent(lower($1)))
            ORDER BY score DESC, level DESC LIMIT $2
        ''', query, limit)
        return [dict(row) for row in rows]

    async def search_knowledge_in_chunks(self, query: str, chunk_ids: List[str], locale: str, limit: int, visibility: str = "PUBLIC") -> List[Dict[str, Any]]:
        if not chunk_ids:
            return []
        await self.connect()
        rows = await self.pool.fetch('''
            SELECT d.id AS document_id, v.id AS version_id, c.id AS chunk_id, d.type::text AS document_type, v.title, c.section,
                   c.content, v."semanticVersion" AS semantic_version, d."authorityLevel" AS authority_level,
                   v."effectiveFrom" AS effective_from, left(v.summary,700) AS parent_summary,
                   (ts_rank_cd(to_tsvector('simple', unaccent(lower(v.title || ' ' || c.section || ' ' || c.content))), plainto_tsquery('simple', unaccent(lower($1)))) + 0.2)::float AS score,
                   COALESCE(sp.url, '/help/' || d.slug) AS public_url
            FROM "KnowledgeChunk" c JOIN "KnowledgeVersion" v ON v.id=c."versionId" JOIN "KnowledgeDocument" d ON d.id=v."documentId"
            LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId"=d.id
            WHERE c.id=ANY($2::text[]) AND d.locale=$3
              AND (d.visibility='PUBLIC' OR ($5='CUSTOMER_AUTHENTICATED' AND d.visibility='CUSTOMER_AUTHENTICATED'))
              AND d."archivedAt" IS NULL AND v.status='PUBLISHED' AND v.searchable=true AND c."retrievalEnabled"=true
              AND v."effectiveFrom"<=now() AND (v."effectiveTo" IS NULL OR v."effectiveTo">now())
            ORDER BY score DESC,d."authorityLevel" DESC LIMIT $4
        ''', query, chunk_ids, locale, limit, visibility)
        return [dict(row) for row in rows]

    async def search_knowledge_graph(self, query: str, locale: str, limit: int, visibility: str = "PUBLIC") -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('''
            WITH query AS (
              SELECT plainto_tsquery('simple', unaccent(lower($1))) AS terms
            ), entity_hits AS (
              SELECT e.id AS entity_id, e."versionId", e."chunkId",
                     GREATEST(0.35, ts_rank_cd(to_tsvector('simple', unaccent(lower(e."canonicalName" || ' ' || e."normalizedKey"))), query.terms))::float AS graph_score
              FROM "KnowledgeEntity" e CROSS JOIN query
              WHERE to_tsvector('simple', unaccent(lower(e."canonicalName" || ' ' || e."normalizedKey"))) @@ query.terms
            ), claim_hits AS (
              SELECT NULL::text AS entity_id, c."versionId", c."chunkId",
                     (LEAST(1.0, c."authorityLevel" / 100.0) + ts_rank_cd(to_tsvector('simple', unaccent(lower(c.subject || ' ' || c.predicate || ' ' || c.value))), query.terms))::float AS graph_score
              FROM "KnowledgeClaim" c CROSS JOIN query
              WHERE to_tsvector('simple', unaccent(lower(c.subject || ' ' || c.predicate || ' ' || c.value))) @@ query.terms
            ), seed_hits AS (
              SELECT entity_id, "versionId", "chunkId", graph_score FROM entity_hits
              UNION ALL
              SELECT entity_id, "versionId", "chunkId", graph_score FROM claim_hits
            ), graph_hits AS (
              SELECT "versionId", "chunkId", graph_score FROM seed_hits
              UNION ALL
              SELECT neighbor."versionId", neighbor."chunkId", (seed.graph_score * edge.weight * 0.72)::float
              FROM entity_hits seed
              JOIN "KnowledgeEdge" edge ON edge."sourceId" = seed.entity_id OR edge."targetId" = seed.entity_id
              JOIN "KnowledgeEntity" neighbor ON neighbor.id = CASE WHEN edge."sourceId" = seed.entity_id THEN edge."targetId" ELSE edge."sourceId" END
            )
            SELECT d.id AS document_id, v.id AS version_id, k.id AS chunk_id, d.type::text AS document_type,
                   v.title, k.section, k.content, v."semanticVersion" AS semantic_version, left(v.summary, 700) AS parent_summary,
                   d."authorityLevel" AS authority_level, v."effectiveFrom" AS effective_from,
                   MAX(g.graph_score) AS score, COALESCE(sp.url, '/help/' || d.slug) AS public_url
            FROM graph_hits g
            JOIN "KnowledgeVersion" v ON v.id = g."versionId"
            JOIN "KnowledgeChunk" k ON k.id = g."chunkId"
            JOIN "KnowledgeDocument" d ON d.id = v."documentId"
            LEFT JOIN "KnowledgeSourcePage" sp ON sp."knowledgeDocumentId" = d.id
            WHERE d.locale = $2 AND (d.visibility = 'PUBLIC' OR ($4 = 'CUSTOMER_AUTHENTICATED' AND d.visibility = 'CUSTOMER_AUTHENTICATED')) AND v.status = 'PUBLISHED' AND v.searchable = true
              AND d."archivedAt" IS NULL AND k."retrievalEnabled" = true
              AND v."effectiveFrom" <= now() AND (v."effectiveTo" IS NULL OR v."effectiveTo" > now())
            GROUP BY d.id, v.id, k.id, sp.url
            ORDER BY score DESC, d."authorityLevel" DESC
            LIMIT $3
        ''', query, locale, limit, visibility)
        return [dict(row) for row in rows]

    async def active_incidents(self) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('SELECT id, title, description, status, severity, "startsAt", scope FROM "ServiceIncident" WHERE status = \'ACTIVE\' AND "startsAt" <= now() AND ("endsAt" IS NULL OR "endsAt" > now()) ORDER BY severity DESC, "startsAt" DESC')
        return [dict(row) for row in rows]

    async def conversation_context(self, conversation_id: str, customer_id: str) -> Dict[str, Any]:
        await self.connect()
        memory, facts, tickets = await asyncio.gather(
            self.pool.fetchrow('SELECT summary,"activeContext","unresolvedQuestions","graphAnchors",version,"updatedAt" FROM "ConversationMemory" WHERE "conversationId"=$1 AND ("customerId"=$2 OR "customerId" IS NULL)', conversation_id, customer_id),
            self.pool.fetch('SELECT category,key,value,confidence,provenance,"expiresAt","updatedAt" FROM "CustomerMemoryFact" WHERE "customerId"=$1 AND active=true AND ("expiresAt" IS NULL OR "expiresAt">now()) ORDER BY "updatedAt" DESC LIMIT 12', customer_id),
            self.pool.fetch('SELECT id,status::text AS status,priority::text AS priority,category,summary,"updatedAt" FROM "Ticket" WHERE "customerId"=$1 AND status::text NOT IN (\'RESOLVED\',\'CLOSED\') ORDER BY "updatedAt" DESC LIMIT 5', customer_id),
        )
        return {
            "memory": dict(memory) if memory else {},
            "facts": [dict(row) for row in facts],
            "openTickets": [dict(row) for row in tickets],
        }

    async def graph_parent_candidates(self, query: str, marketplace: str, limit: int = 20, phrases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch(r'''
            WITH eligible AS (
              SELECT e.id, e.type, e."canonicalName", e."normalizedKey", e."versionId",
                     d.id AS document_id, d.type AS document_type, d."authorityLevel" AS authority_level,
                     v.title, v.summary,
                       unaccent(normalize(lower(e."canonicalName" || ' ' || v.title || ' ' || v.summary), NFC)) AS searchable_text,
                       unaccent(normalize(lower(e."canonicalName" || ' ' || v.title), NFC)) AS title_text
              FROM "KnowledgeEntity" e
              JOIN "KnowledgeVersion" v ON v.id=e."versionId"
              JOIN "KnowledgeDocument" d ON d.id=v."documentId"
              WHERE d.marketplace=$2::"KnowledgeMarketplace" AND d."currentVersionId"=v.id
                AND d."archivedAt" IS NULL AND v.status='PUBLISHED' AND v.searchable=true
            ), term_scores AS (
              SELECT item.id, SUM(CASE WHEN unaccent(normalize(lower(item."canonicalName"), NFC)) LIKE '%' || unaccent(normalize(term.value, NFC)) || '%' THEN 3 ELSE 1 END)::float AS score
              FROM eligible item CROSS JOIN LATERAL regexp_split_to_table(lower($1), '\s+') AS term(value)
              WHERE length(term.value)>=3 AND item.searchable_text LIKE '%' || unaccent(normalize(term.value, NFC)) || '%'
              GROUP BY item.id HAVING count(DISTINCT term.value)>=2
            ), phrase_scores AS (
                SELECT item.id, SUM(
                  CASE
                    WHEN item.title_text LIKE '%' || unaccent(normalize(lower(phrase.value), NFC)) || '%' THEN 16
                    ELSE 8
                  END
                )::float AS score
              FROM eligible item CROSS JOIN unnest($4::text[]) AS phrase(value)
              WHERE item.searchable_text LIKE '%' || unaccent(normalize(lower(phrase.value), NFC)) || '%'
              GROUP BY item.id
            ), scores AS (
              SELECT id, SUM(score)::float AS score FROM (
                SELECT * FROM term_scores UNION ALL SELECT * FROM phrase_scores
              ) combined GROUP BY id
            )
            SELECT item.id, item.type::text AS type, item."canonicalName" AS name, item."normalizedKey" AS normalized_key,
                   item.document_id, item.document_type::text AS document_type, item.authority_level,
                   item.title, left(item.summary,320) AS summary, scores.score,
                   COALESCE(term_scores.score,0)::float AS term_score, COALESCE(phrase_scores.score,0)::float AS phrase_score
            FROM eligible item JOIN scores ON scores.id=item.id
            LEFT JOIN term_scores ON term_scores.id=item.id
            LEFT JOIN phrase_scores ON phrase_scores.id=item.id
            ORDER BY scores.score DESC, item.authority_level DESC
            LIMIT $3
        ''', query, marketplace, limit, phrases or [])
        return [dict(row) for row in rows]

    async def rebuild_knowledge_graph(self) -> Dict[str, int]:
        await self.connect()
        rows = await self.pool.fetch('''
            SELECT v.id AS version_id, v.title, v."effectiveFrom", v."effectiveTo",
                   d.id AS document_id, d.type::text AS document_type, d.visibility::text AS visibility,
                   d."authorityLevel" AS authority_level, d."categoryId" AS category_id,
                   c.id AS chunk_id, c.section, c.content
            FROM "KnowledgeVersion" v
            JOIN "KnowledgeDocument" d ON d.id = v."documentId"
            JOIN "KnowledgeChunk" c ON c."versionId" = v.id AND c."retrievalEnabled" = true
            WHERE v.status = 'PUBLISHED' AND v.searchable = true AND d."currentVersionId" = v.id AND d.marketplace = 'SHOPEE'
            ORDER BY v.id, c.id
        ''')
        versions: Dict[str, List[asyncpg.Record]] = {}
        for row in rows:
            versions.setdefault(row["version_id"], []).append(row)
        totals = {"builds": 0, "entities": 0, "edges": 0, "claims": 0}
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for version_id, chunks in versions.items():
                    row = chunks[0]
                    await connection.execute('DELETE FROM "KnowledgeEdge" WHERE "versionId" = $1', version_id)
                    await connection.execute('DELETE FROM "KnowledgeClaim" WHERE "versionId" = $1', version_id)
                    await connection.execute('DELETE FROM "KnowledgeEntity" WHERE "versionId" = $1', version_id)
                    await connection.execute('DELETE FROM "KnowledgeGraphBuild" WHERE "versionId" = $1', version_id)
                    build_id, document_entity_id, domain_entity_id = str(uuid4()), str(uuid4()), str(uuid4())
                    document_type = row["document_type"]
                    document_entity_type = "INCIDENT" if document_type == "INCIDENT" else "POLICY_RULE" if document_type in {"POLICY", "TERMS"} else "PRODUCT" if document_type in {"PRODUCT_GUIDE", "TROUBLESHOOTING"} else "CONCEPT"
                    hierarchy_relation = "GOVERNED_BY" if document_type in {"POLICY", "TERMS"} else "AFFECTED_BY" if document_type == "INCIDENT" else "RELATED_TO"
                    await connection.execute('INSERT INTO "KnowledgeEntity" (id,"versionId","chunkId",type,"canonicalName","normalizedKey",metadata,"createdAt") VALUES ($1,$2,$3,$4::"KnowledgeEntityType",$5,$6,$7::jsonb,now())', document_entity_id, version_id, row["chunk_id"], document_entity_type, row["title"], f'document-{row["document_id"]}', json.dumps({"level": "DOCUMENT", "categoryId": row["category_id"]}))
                    await connection.execute('INSERT INTO "KnowledgeEntity" (id,"versionId","chunkId",type,"canonicalName","normalizedKey",metadata,"createdAt") VALUES ($1,$2,$3,\'INTENT\',$4,$5,$6::jsonb,now())', domain_entity_id, version_id, row["chunk_id"], row["category_id"], f'domain-{row["category_id"]}', json.dumps({"level": "DOMAIN"}))
                    await connection.execute('INSERT INTO "KnowledgeEdge" (id,"versionId","chunkId","sourceId","targetId",relation,weight,metadata,"createdAt") VALUES ($1,$2,$3,$4,$5,$6::"KnowledgeRelationType",$7,$8::jsonb,now())', str(uuid4()), version_id, row["chunk_id"], document_entity_id, domain_entity_id, hierarchy_relation, row["authority_level"] / 100, json.dumps({"hierarchy": True}))
                    claim_count = 0
                    for chunk in chunks:
                        section_entity_id = str(uuid4())
                        await connection.execute('INSERT INTO "KnowledgeEntity" (id,"versionId","chunkId",type,"canonicalName","normalizedKey",metadata,"createdAt") VALUES ($1,$2,$3,\'CONCEPT\',$4,$5,$6::jsonb,now())', section_entity_id, version_id, chunk["chunk_id"], chunk["section"], f'section-{chunk["chunk_id"]}', json.dumps({"level": "SECTION", "documentId": row["document_id"], "categoryId": row["category_id"]}))
                        await connection.execute('INSERT INTO "KnowledgeEdge" (id,"versionId","chunkId","sourceId","targetId",relation,weight,metadata,"createdAt") VALUES ($1,$2,$3,$4,$5,$6::"KnowledgeRelationType",$7,$8::jsonb,now())', str(uuid4()), version_id, chunk["chunk_id"], section_entity_id, document_entity_id, hierarchy_relation, 0.9, json.dumps({"hierarchy": True}))
                        if document_type in {"POLICY", "TERMS", "FAQ", "INCIDENT"}:
                            await connection.execute('INSERT INTO "KnowledgeClaim" (id,"versionId","chunkId",subject,predicate,value,polarity,"authorityLevel","effectiveFrom","effectiveTo",scope,"createdAt") VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,now())', str(uuid4()), version_id, chunk["chunk_id"], chunk["section"], "service_status" if document_type == "INCIDENT" else "answers" if document_type == "FAQ" else "governs", chunk["content"], -1 if "không được" in chunk["content"].lower() or "cấm" in chunk["content"].lower() else 1, row["authority_level"], row["effectiveFrom"], row["effectiveTo"], json.dumps({"categoryId": row["category_id"], "documentId": row["document_id"]}))
                            claim_count += 1
                    entity_count = 2 + len(chunks)
                    edge_count = 1 + len(chunks)
                    await connection.execute('INSERT INTO "KnowledgeGraphBuild" (id, "versionId", status, "extractorVersion", "entityCount", "edgeCount", "claimCount", "startedAt", "completedAt", "createdAt") VALUES ($1,$2,\'COMPLETED\',\'hierarchical-2.0\',$3,$4,$5,now(),now(),now())', build_id, version_id, entity_count, edge_count, claim_count)
                    totals["builds"] += 1; totals["entities"] += entity_count; totals["edges"] += edge_count; totals["claims"] += claim_count
        return totals

    async def create_ticket(self, customer_id: Optional[str], conversation_id: str, order_id: Optional[str], category: str, summary: str, priority: str, ticket_id: str) -> str:
        await self.connect()
        await self.pool.execute('''
            INSERT INTO "Ticket" (id, "customerId", "orderId", "conversationId", status, priority, category, summary, "createdAt", "updatedAt")
            VALUES ($1, $2, $3, $4, 'NEED_HUMAN', $5::"Priority", $6, $7, now(), now())
            ON CONFLICT (id) DO NOTHING
        ''', ticket_id, customer_id, order_id, conversation_id, priority, category, summary)
        return ticket_id

    async def ticket_exists(self, ticket_id: str) -> bool:
        await self.connect()
        return bool(await self.pool.fetchval('SELECT EXISTS(SELECT 1 FROM "Ticket" WHERE id=$1)', ticket_id))

    async def create_handoff_ticket(self, ticket_id: str, customer_id: Optional[str], conversation_id: str, order_id: Optional[str], category: str, summary: str, priority: str, context: Dict[str, Any]) -> str:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('''
                    INSERT INTO "Ticket" (id, "customerId", "orderId", "conversationId", status, priority, category, summary, "createdAt", "updatedAt")
                    VALUES ($1,$2,$3,$4,'NEED_HUMAN',$5::"Priority",$6,$7,now(),now())
                    ON CONFLICT (id) DO UPDATE SET "updatedAt"=now()
                ''', ticket_id, customer_id, order_id, conversation_id, priority, category, summary[:1000])
                await connection.execute('INSERT INTO "TicketEvent" (id,"ticketId",type,payload,"createdAt") VALUES ($1,$2,\'AI_HANDOFF\',$3::jsonb,now())', f"te_{uuid4().hex}", ticket_id, json.dumps(context, ensure_ascii=False, default=str))
        return ticket_id

    async def record_knowledge_gap(self, query: str, reason: str) -> str:
        await self.connect()
        row = await self.pool.fetchrow('''
            INSERT INTO "KnowledgeGap" (id, query, reason, occurrences, status, "createdAt", "updatedAt")
            VALUES ('kg_' || substr(md5($1 || ':' || $2), 1, 20), $1, $2, 1, 'OPEN', now(), now())
            ON CONFLICT (id) DO UPDATE SET occurrences = "KnowledgeGap".occurrences + 1, "updatedAt" = now()
            RETURNING id
        ''', query[:2000], reason[:200])
        return str(row["id"])

    async def cancel_order(self, customer_id: str, conversation_id: str, order_id: str, reason: str, action_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                order = await connection.fetchrow('SELECT id, status::text AS status FROM "Order" WHERE id=$1 AND "customerId"=$2 FOR UPDATE', order_id, customer_id)
                if not order:
                    return None
                if order["status"] not in {"PENDING", "CONFIRMED", "PROCESSING"}:
                    return {"id": order_id, "status": order["status"], "actionStatus": "INVALID_STATE"}
                await connection.execute('UPDATE "Order" SET status=\'CANCELLED\', "updatedAt"=now() WHERE id=$1', order_id)
                await connection.execute('''INSERT INTO "CommerceAction" (id,"customerId","orderId","conversationId",type,status,payload,result,"createdAt","updatedAt")
                    VALUES ($1,$2,$3,$4,'CANCEL_ORDER','COMPLETED',jsonb_build_object('reason',$5::text),jsonb_build_object('orderStatus','CANCELLED'),now(),now()) ON CONFLICT (id) DO NOTHING''', action_id, customer_id, order_id, conversation_id, reason)
                return {"id": order_id, "status": "CANCELLED", "actionId": action_id, "actionStatus": "COMPLETED"}

    async def create_commerce_action(self, customer_id: str, conversation_id: str, order_id: str, action_type: str, payload: Dict[str, Any], action_id: str, allowed_statuses: set[str]) -> Optional[Dict[str, Any]]:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                order = await connection.fetchrow('SELECT id, status::text AS status FROM "Order" WHERE id=$1 AND "customerId"=$2 FOR UPDATE', order_id, customer_id)
                if not order:
                    return None
                if order["status"] not in allowed_statuses:
                    return {"id": order_id, "status": order["status"], "actionStatus": "INVALID_STATE"}
                await connection.execute('''INSERT INTO "CommerceAction" (id,"customerId","orderId","conversationId",type,status,payload,result,"createdAt","updatedAt")
                    VALUES ($1,$2,$3,$4,$5,'COMPLETED',$6::jsonb,jsonb_build_object('orderStatus',$7::text),now(),now()) ON CONFLICT (id) DO NOTHING''', action_id, customer_id, order_id, conversation_id, action_type, json.dumps(payload), order["status"])
                return {"id": order_id, "status": order["status"], "actionId": action_id, "actionType": action_type, "actionStatus": "COMPLETED"}

    async def create_refund(self, customer_id: str, conversation_id: str, order_id: str, reason: str, action_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                order = await connection.fetchrow('SELECT id, status::text AS status, "totalAmount" FROM "Order" WHERE id=$1 AND "customerId"=$2 FOR UPDATE', order_id, customer_id)
                if not order:
                    return None
                if order["status"] not in {"DELIVERED", "CANCELLED"}:
                    return {"id": order_id, "status": order["status"], "actionStatus": "INVALID_STATE"}
                refund_id = f"refund_{action_id}"
                await connection.execute('''INSERT INTO "Refund" (id,"orderId",status,amount,reason,"observedAt","referenceId")
                    VALUES ($1,$2,'PROCESSING',$3,$4,now(),$5) ON CONFLICT (id) DO NOTHING''', refund_id, order_id, order["totalAmount"], reason, action_id)
                await connection.execute('''INSERT INTO "CommerceAction" (id,"customerId","orderId","conversationId",type,status,payload,result,"createdAt","updatedAt")
                    VALUES ($1,$2,$3,$4,'CREATE_REFUND','COMPLETED',jsonb_build_object('reason',$5::text),jsonb_build_object('refundId',$6::text,'refundStatus','PROCESSING'),now(),now()) ON CONFLICT (id) DO NOTHING''', action_id, customer_id, order_id, conversation_id, reason, refund_id)
                return {"id": refund_id, "orderId": order_id, "status": "PROCESSING", "actionId": action_id, "actionStatus": "COMPLETED"}

    async def search_products(self, query: str, category: Optional[str] = None, max_price: Optional[float] = None, limit: int = 8) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('''
            SELECT id, sku, name, category, brand, description, price, stock, rating, "soldCount", metadata
            FROM "Product"
            WHERE active=true AND stock>0
              AND ($1='' OR unaccent(lower(name)) LIKE '%' || unaccent(lower($1)) || '%'
                OR unaccent(lower(description)) LIKE '%' || unaccent(lower($1)) || '%'
                OR unaccent(lower(brand)) LIKE '%' || unaccent(lower($1)) || '%'
                OR similarity(unaccent(lower(name)), unaccent(lower($1))) >= 0.32
                OR word_similarity(unaccent(lower($1)), unaccent(lower(name))) >= 0.34)
              AND ($2::text IS NULL OR category=$2)
              AND ($3::numeric IS NULL OR price <= $3)
            ORDER BY CASE WHEN $1='' THEN 0 ELSE GREATEST(
                similarity(unaccent(lower(name)), unaccent(lower($1))),
                word_similarity(unaccent(lower($1)), unaccent(lower(name)))
              ) END DESC, rating DESC, "soldCount" DESC, price ASC LIMIT $4
        ''', query.strip(), category, max_price, limit)
        return [dict(row) for row in rows]

    async def product_details(self, product_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('SELECT id, sku, name, category, brand, description, price, stock, rating, "soldCount", metadata FROM "Product" WHERE id=$1 AND active=true', product_id)
        return dict(row) if row else None

    async def customer_addresses(self, customer_id: str) -> List[Dict[str, Any]]:
        await self.connect()
        rows = await self.pool.fetch('SELECT id, label, recipient, line1, city, country FROM "Address" WHERE "customerId"=$1 ORDER BY label, id', customer_id)
        return [dict(row) for row in rows]

    async def create_checkout_session(self, checkout_id: str, customer_id: str, conversation_id: str, product_id: str, quantity: int) -> Optional[Dict[str, Any]]:
        await self.connect()
        product = await self.pool.fetchrow('SELECT id, name, price, stock FROM "Product" WHERE id=$1 AND active=true', product_id)
        if not product or quantity < 1 or quantity > product["stock"]:
            return None
        total = product["price"] * quantity
        row = await self.pool.fetchrow('''
            INSERT INTO "CheckoutSession" (id,"customerId","conversationId","productId",quantity,"unitPrice","totalAmount",status,"createdAt","updatedAt","expiresAt")
            VALUES ($1,$2,$3,$4,$5,$6,$7,'DRAFT',now(),now(),now()+interval '30 minutes')
            ON CONFLICT (id) DO UPDATE SET quantity=EXCLUDED.quantity,"totalAmount"=EXCLUDED."totalAmount","updatedAt"=now()
            RETURNING id,"productId",quantity,"unitPrice","totalAmount",status,"expiresAt"
        ''', checkout_id, customer_id, conversation_id, product_id, quantity, product["price"], total)
        return {**dict(row), "productName": product["name"], "stock": product["stock"]}

    async def update_checkout(self, checkout_id: str, customer_id: str, address_id: Optional[str] = None, payment_method: Optional[str] = None) -> Optional[Dict[str, Any]]:
        await self.connect()
        if address_id and not await self.pool.fetchval('SELECT EXISTS(SELECT 1 FROM "Address" WHERE id=$1 AND "customerId"=$2)', address_id, customer_id):
            return None
        row = await self.pool.fetchrow('''
            UPDATE "CheckoutSession" SET "addressId"=COALESCE($3,"addressId"), "paymentMethod"=COALESCE($4,"paymentMethod"), "updatedAt"=now()
            WHERE id=$1 AND "customerId"=$2 AND status='DRAFT' AND "expiresAt">now()
            RETURNING id,"productId","addressId",quantity,"paymentMethod","unitPrice","totalAmount",status,"expiresAt"
        ''', checkout_id, customer_id, address_id, payment_method)
        return dict(row) if row else None

    async def checkout_details(self, checkout_id: str, customer_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        row = await self.pool.fetchrow('''SELECT c.id,c."productId",c."addressId",c.quantity,c."paymentMethod",c."unitPrice",c."totalAmount",c.status,c."orderId",c."expiresAt",p.name AS "productName",p.stock,a.label AS "addressLabel",a.line1,a.city
            FROM "CheckoutSession" c JOIN "Product" p ON p.id=c."productId" LEFT JOIN "Address" a ON a.id=c."addressId" WHERE c.id=$1 AND c."customerId"=$2''', checkout_id, customer_id)
        return dict(row) if row else None

    async def confirm_checkout(self, checkout_id: str, customer_id: str) -> Optional[Dict[str, Any]]:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                checkout = await connection.fetchrow('SELECT * FROM "CheckoutSession" WHERE id=$1 AND "customerId"=$2 FOR UPDATE', checkout_id, customer_id)
                if not checkout:
                    return None
                if checkout["status"] == "COMPLETED":
                    return {"checkoutId": checkout_id, "orderId": checkout["orderId"], "status": "COMPLETED", "idempotent": True}
                if checkout["expiresAt"] <= datetime.utcnow() or not checkout["addressId"] or checkout["paymentMethod"] not in {"COD", "ONLINE_SIMULATED"}:
                    return {"checkoutId": checkout_id, "status": "INVALID_CHECKOUT"}
                product = await connection.fetchrow('SELECT id,name,price,stock FROM "Product" WHERE id=$1 AND active=true FOR UPDATE', checkout["productId"])
                if not product or product["stock"] < checkout["quantity"] or product["price"] != checkout["unitPrice"]:
                    return {"checkoutId": checkout_id, "status": "PRICE_OR_STOCK_CHANGED"}
                order_id = f"ORD-{uuid4().hex[:10].upper()}"
                payment_id = f"pay_{order_id}"
                await connection.execute('INSERT INTO "Order" (id,"customerId",status,"totalAmount",currency,"placedAt","updatedAt") VALUES ($1,$2,\'CONFIRMED\',$3,\'VND\',now(),now())', order_id, customer_id, checkout["totalAmount"])
                await connection.execute('INSERT INTO "OrderItem" (id,"orderId","productId",quantity,"unitPrice") VALUES ($1,$2,$3,$4,$5)', str(uuid4()), order_id, checkout["productId"], checkout["quantity"], checkout["unitPrice"])
                await connection.execute('INSERT INTO "Payment" (id,"orderId",provider,status,amount,currency,"maskedReference","observedAt") VALUES ($1,$2,$3,\'PENDING\',$4,\'VND\',$5,now())', payment_id, order_id, checkout["paymentMethod"], checkout["totalAmount"], f"SIM-***{order_id[-4:]}")
                await connection.execute('UPDATE "Product" SET stock=stock-$2,"soldCount"="soldCount"+$2 WHERE id=$1', checkout["productId"], checkout["quantity"])
                await connection.execute('UPDATE "CheckoutSession" SET status=\'COMPLETED\',"orderId"=$2,"updatedAt"=now() WHERE id=$1', checkout_id, order_id)
                return {"checkoutId": checkout_id, "orderId": order_id, "status": "COMPLETED", "totalAmount": checkout["totalAmount"], "paymentMethod": checkout["paymentMethod"], "productName": product["name"], "quantity": checkout["quantity"]}

    async def start_ai_run(self, conversation_id: str, prompt_version: str) -> str:
        await self.connect()
        run_id = f"airun_{uuid4().hex}"
        await self.pool.execute('INSERT INTO "AiRun" (id,"conversationId","promptVersion","startedAt","requiresHuman") VALUES ($1,$2,$3,now(),false)', run_id, conversation_id, prompt_version)
        return run_id

    async def record_ai_step(self, run_id: str, name: str, status: str, latency_ms: int, summary: Dict[str, Any]) -> None:
        await self.connect()
        await self.pool.execute('INSERT INTO "AiStep" (id,"runId",name,status,"latencyMs",summary) VALUES ($1,$2,$3,$4,$5,$6::jsonb)', f"aistep_{uuid4().hex}", run_id, name, status, latency_ms, json.dumps(summary, default=str))

    async def record_ai_tool_call(self, run_id: str, name: str, status: str, reference_id: Optional[str], latency_ms: int = 0) -> None:
        await self.connect()
        await self.pool.execute('''INSERT INTO "AiToolCall" (id,"runId","toolName",status,"referenceId","inputRedacted","outputRedacted","latencyMs","createdAt")
            VALUES ($1,$2,$3,$4::"ToolCallStatus",$5,'{}'::jsonb,jsonb_build_object('status',$4::text),$6,now())''', f"aitool_{uuid4().hex}", run_id, name, status, reference_id, latency_ms)

    async def record_ai_retrieval(self, run_id: str, document_id: str, semantic_version: str, score: float, rank: int) -> None:
        await self.connect()
        row = await self.pool.fetchrow('''SELECT v.id AS version_id, c.id AS chunk_id FROM "KnowledgeVersion" v
            JOIN "KnowledgeChunk" c ON c."versionId"=v.id AND c."retrievalEnabled"=true
            WHERE v."documentId"=$1 AND v."semanticVersion"=$2 ORDER BY c.id LIMIT 1''', document_id, semantic_version)
        if row:
            await self.pool.execute('INSERT INTO "AiRetrievalResult" (id,"runId","versionId","chunkId",score,rank) VALUES ($1,$2,$3,$4,$5,$6)', f"airet_{uuid4().hex}", run_id, row["version_id"], row["chunk_id"], score, rank)

    async def finish_ai_run(self, run_id: str, intent: Optional[str], confidence: float, requires_human: bool) -> None:
        await self.connect()
        await self.pool.execute('UPDATE "AiRun" SET intent=$2,confidence=$3,"requiresHuman"=$4,"completedAt"=now() WHERE id=$1', run_id, intent, confidence, requires_human)

    async def persist_ai_trace(
        self,
        run_id: str,
        conversation_id: str,
        prompt_version: str,
        intent: Optional[str],
        confidence: float,
        requires_human: bool,
        steps: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
        retrievals: List[Dict[str, Any]],
    ) -> None:
        await self.connect()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    'INSERT INTO "AiRun" (id,"conversationId","promptVersion",intent,confidence,"requiresHuman","startedAt","completedAt") VALUES ($1,$2,$3,$4,$5,$6,now(),now())',
                    run_id, conversation_id, prompt_version, intent, confidence, requires_human,
                )
                if steps:
                    await connection.executemany(
                        'INSERT INTO "AiStep" (id,"runId",name,status,"latencyMs",summary) VALUES ($1,$2,$3,$4,$5,$6::jsonb)',
                        [(f"aistep_{uuid4().hex}", run_id, item["name"], item.get("status", "COMPLETED"), int(item.get("latency_ms", 0)), json.dumps(item.get("summary") or {}, default=str)) for item in steps],
                    )
                if tool_calls:
                    await connection.executemany(
                        '''INSERT INTO "AiToolCall" (id,"runId","toolName",status,"referenceId","inputRedacted","outputRedacted","latencyMs","createdAt")
                           VALUES ($1,$2,$3,$4::"ToolCallStatus",$5,'{}'::jsonb,jsonb_build_object('status',$4::text),$6,now())''',
                        [(f"aitool_{uuid4().hex}", run_id, item["name"], item["status"], item.get("reference_id"), int(item.get("latency_ms", 0))) for item in tool_calls],
                    )
                for rank, item in enumerate(retrievals, 1):
                    row = await connection.fetchrow(
                        '''SELECT v.id AS version_id, c.id AS chunk_id FROM "KnowledgeVersion" v
                           JOIN "KnowledgeChunk" c ON c."versionId"=v.id AND c."retrievalEnabled"=true
                           WHERE v."documentId"=$1 AND v."semanticVersion"=$2 ORDER BY c.id LIMIT 1''',
                        item["document_id"], item["version"],
                    )
                    if row:
                        await connection.execute(
                            'INSERT INTO "AiRetrievalResult" (id,"runId","versionId","chunkId",score,rank) VALUES ($1,$2,$3,$4,$5,$6)',
                            f"airet_{uuid4().hex}", run_id, row["version_id"], row["chunk_id"], float(item.get("score") or 0), rank,
                        )


repository = Repository()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
