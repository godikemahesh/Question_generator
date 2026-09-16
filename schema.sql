-- ==============================================================================
-- ExamForge AI Question Generation & Ingestion Platform - Supabase Schema
-- Run this script in the Supabase SQL Editor (https://supabase.com/dashboard)
-- ==============================================================================

-- Enable UUID extension if not enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- 1. App Configuration Table (Endpoints, Keys, Generation Settings)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_config (
    id TEXT PRIMARY KEY DEFAULT 'global',
    examforge_url TEXT NOT NULL DEFAULT 'https://examforge-pink.vercel.app/api/questions/ai-ingest',
    examforge_api_key TEXT NOT NULL DEFAULT 'ef_ai_ingest_9a7d3f28e6c41b80d52a7e9140f',
    batch_size INT NOT NULL DEFAULT 100,
    auto_dispatch BOOLEAN NOT NULL DEFAULT true,
    active_provider TEXT NOT NULL DEFAULT 'gemini', -- 'gemini', 'openrouter', 'groq'
    gemini_api_key TEXT DEFAULT '',
    openrouter_api_key TEXT DEFAULT '',
    groq_api_key TEXT DEFAULT '',
    tavily_api_key TEXT DEFAULT '',
    brave_api_key TEXT DEFAULT '',
    exa_api_key TEXT DEFAULT '',
    web_search_enabled BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert default config
INSERT INTO app_config (id, examforge_url, examforge_api_key, batch_size, auto_dispatch)
VALUES ('global', 'https://examforge-pink.vercel.app/api/questions/ai-ingest', 'ef_ai_ingest_9a7d3f28e6c41b80d52a7e9140f', 100, true)
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------------------------------------
-- 2. Admin Users Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed primary admin user: maheshgodike17@gmail.com / Maheshg17#
INSERT INTO admin_users (email, password_hash, role)
VALUES ('maheshgodike17@gmail.com', '$2b$12$5mwTsiG0F/GSA/B1OHjmLOTOKnXmobDv19GhIfDFsJcI73aMHj0t6', 'admin')
ON CONFLICT (email) DO UPDATE 
SET password_hash = '$2b$12$5mwTsiG0F/GSA/B1OHjmLOTOKnXmobDv19GhIfDFsJcI73aMHj0t6';

-- ------------------------------------------------------------------------------
-- 3. Subjects Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    exam_code VARCHAR(30) NOT NULL DEFAULT 'RRB',
    is_active BOOLEAN NOT NULL DEFAULT true,
    speed_delay_seconds INT NOT NULL DEFAULT 15,
    target_count INT NOT NULL DEFAULT 120,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed initial subjects
INSERT INTO subjects (name, exam_code, is_active, speed_delay_seconds, target_count) VALUES
('Science', 'RRB', true, 15, 120),
('Mathematics', 'RRB', true, 15, 120),
('General Knowledge', 'RRB', true, 15, 120),
('Disability', 'DSC', true, 15, 120),
('Perspectives Special Ed', 'DSC', true, 15, 120),
('Psychology', 'DSC', true, 15, 120),
('Sped Methodology', 'DSC', true, 15, 120)
ON CONFLICT (name) DO NOTHING;

-- ------------------------------------------------------------------------------
-- 4. Syllabi & Topic Trees Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS syllabi (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID REFERENCES subjects(id) ON DELETE CASCADE,
    subject_name TEXT NOT NULL UNIQUE,
    exam_code VARCHAR(30) NOT NULL DEFAULT 'RRB',
    raw_text TEXT,
    parsed_hierarchy JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------------------------
-- 5. Questions Bank & Dedup Registry Table (English Only)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_name TEXT NOT NULL,
    topic_name TEXT NOT NULL DEFAULT 'General',
    exam_code VARCHAR(30) NOT NULL DEFAULT 'RRB',
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_answer VARCHAR(5) NOT NULL, -- 'A', 'B', 'C', 'D'
    explanation TEXT NOT NULL DEFAULT '',
    difficulty VARCHAR(20) NOT NULL DEFAULT 'Medium', -- 'Easy', 'Medium', 'Hard'
    tags TEXT NOT NULL DEFAULT '',
    normalized_hash TEXT NOT NULL UNIQUE, -- SHA-256 for zero duplicates
    status VARCHAR(30) NOT NULL DEFAULT 'APPROVED', -- 'APPROVED', 'READY_TO_DISPATCH', 'DISPATCHED', 'REJECTED'
    batch_id TEXT,
    dispatched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject_name);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_hash ON questions(normalized_hash);

-- ------------------------------------------------------------------------------
-- 6. Dispatch Batches Table (Audit & Delivery History)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dispatch_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_number TEXT NOT NULL UNIQUE,
    exam_code VARCHAR(30) NOT NULL,
    subject_name TEXT NOT NULL,
    topic_name TEXT NOT NULL,
    question_count INT NOT NULL DEFAULT 100,
    endpoint_url TEXT NOT NULL,
    status_code INT,
    response_payload JSONB,
    questions_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dispatch_created ON dispatch_batches(created_at DESC);

-- Enable Row Level Security (RLS) - Defaults to allowed for Service Role / Authenticated
ALTER TABLE app_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE syllabi ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE dispatch_batches ENABLE ROW LEVEL SECURITY;

-- Allow full access for service_role and anon if using key
CREATE POLICY "Allow service role full access" ON app_config FOR ALL USING (true);
CREATE POLICY "Allow service role full access subjects" ON subjects FOR ALL USING (true);
CREATE POLICY "Allow service role full access syllabi" ON syllabi FOR ALL USING (true);
CREATE POLICY "Allow service role full access questions" ON questions FOR ALL USING (true);
CREATE POLICY "Allow service role full access dispatch_batches" ON dispatch_batches FOR ALL USING (true);
CREATE POLICY "Allow service role full access admin_users" ON admin_users FOR ALL USING (true);
