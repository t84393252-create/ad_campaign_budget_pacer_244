-- Database initialization for Ad Campaign Budget Pacer
-- PostgreSQL version

-- Campaigns table
CREATE TABLE IF NOT EXISTS campaigns (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    daily_budget_cents BIGINT NOT NULL,
    total_budget_cents BIGINT,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    pacing_mode VARCHAR(20) NOT NULL DEFAULT 'EVEN',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_dates ON campaigns(start_date, end_date);

-- Pacing configurations for traffic patterns
CREATE TABLE IF NOT EXISTS pacing_configs (
    id SERIAL PRIMARY KEY,
    campaign_id VARCHAR(50) NOT NULL,
    hour_of_day INT NOT NULL,
    multiplier DECIMAL(4,2) NOT NULL DEFAULT 1.0,
    day_of_week INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, hour_of_day, day_of_week)
);

CREATE INDEX IF NOT EXISTS idx_campaign_hour ON pacing_configs(campaign_id, hour_of_day);

-- Detailed spend tracking log
CREATE TABLE IF NOT EXISTS spend_log (
    id BIGSERIAL PRIMARY KEY,
    campaign_id VARCHAR(50) NOT NULL,
    amount_cents BIGINT NOT NULL,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hour_bucket TIMESTAMP NOT NULL,
    day_bucket DATE NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_campaign_time ON spend_log(campaign_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_buckets ON spend_log(campaign_id, hour_bucket, day_bucket);

-- Budget alerts and circuit breaker events
CREATE TABLE IF NOT EXISTS budget_alerts (
    id SERIAL PRIMARY KEY,
    campaign_id VARCHAR(50) NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    threshold_percentage DECIMAL(5,2),
    message TEXT,
    circuit_breaker_state VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_campaign_alerts ON budget_alerts(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_unresolved ON budget_alerts(campaign_id, resolved_at);

-- Historical pacing performance for ML optimization
CREATE TABLE IF NOT EXISTS pacing_history (
    id BIGSERIAL PRIMARY KEY,
    campaign_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    hour INT NOT NULL,
    planned_spend_cents BIGINT NOT NULL,
    actual_spend_cents BIGINT NOT NULL,
    impressions INT DEFAULT 0,
    clicks INT DEFAULT 0,
    pacing_accuracy DECIMAL(5,2),
    throttle_rate DECIMAL(5,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE(campaign_id, date, hour)
);

CREATE INDEX IF NOT EXISTS idx_campaign_date ON pacing_history(campaign_id, date);
CREATE INDEX IF NOT EXISTS idx_accuracy ON pacing_history(pacing_accuracy);

-- Real-time budget status cache (for quick lookups)
CREATE TABLE IF NOT EXISTS budget_status_cache (
    campaign_id VARCHAR(50) PRIMARY KEY,
    daily_budget_cents BIGINT NOT NULL,
    daily_spent_cents BIGINT DEFAULT 0,
    hourly_spent_cents BIGINT DEFAULT 0,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    circuit_breaker_state VARCHAR(20) DEFAULT 'CLOSED',
    throttle_rate DECIMAL(5,4) DEFAULT 0.0,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_last_update ON budget_status_cache(last_update);

-- Aggregated metrics for reporting
CREATE TABLE IF NOT EXISTS daily_metrics (
    campaign_id VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    total_spend_cents BIGINT DEFAULT 0,
    total_impressions BIGINT DEFAULT 0,
    total_clicks BIGINT DEFAULT 0,
    pacing_accuracy DECIMAL(5,2),
    circuit_breaker_trips INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (campaign_id, date),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_date ON daily_metrics(date);

-- Sample data for testing
INSERT INTO campaigns (id, name, daily_budget_cents, total_budget_cents, start_date, end_date, pacing_mode) VALUES
('camp-001', 'Test Campaign 1', 1000000, 30000000, NOW(), NOW() + INTERVAL '30 days', 'EVEN'),
('camp-002', 'Test Campaign 2', 500000, 15000000, NOW(), NOW() + INTERVAL '30 days', 'ASAP'),
('camp-003', 'Test Campaign 3', 2000000, 60000000, NOW(), NOW() + INTERVAL '30 days', 'FRONT_LOADED')
ON CONFLICT (id) DO NOTHING;

-- Sample pacing configurations (peak hours)
INSERT INTO pacing_configs (campaign_id, hour_of_day, multiplier) VALUES
('camp-001', 9, 1.5),
('camp-001', 10, 1.8),
('camp-001', 11, 2.0),
('camp-001', 12, 1.8),
('camp-001', 13, 1.5),
('camp-001', 14, 1.3),
('camp-001', 18, 1.6),
('camp-001', 19, 1.8),
('camp-001', 20, 1.5)
ON CONFLICT (campaign_id, hour_of_day, day_of_week) DO NOTHING;