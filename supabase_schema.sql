-- Run once in the Supabase SQL editor.
-- MVP security model: private Streamlit server + password gate + fixed default_user scope.
-- Before supporting multiple users, replace the anon policies below with Supabase Auth
-- policies based on auth.uid() and change user_id columns to uuid foreign keys.

create extension if not exists pgcrypto;

create table if not exists public.holdings (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  instrument text, isin text, ticker_id text, price_symbol text, asset_type text,
  category text, theme text, region text, currency text default 'EUR',
  quantity numeric default 0, manual_current_price numeric default 0, live_current_price numeric,
  price_source text, fx_rate_to_eur numeric default 1, current_value_eur numeric default 0,
  buy_in_value_eur numeric default 0, pl_eur numeric default 0, pl_percent numeric default 0,
  direct_trading_allowed boolean default true, fractional_allowed boolean default false,
  notes text, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists public.candidate_assets (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  instrument text, isin text, ticker_id text, price_symbol text, asset_type text,
  category text, theme text, region text, currency text default 'EUR', ter_percent numeric,
  fund_size_eur numeric, replication_method text, distribution_policy text, domicile text,
  savings_plan_available boolean default false, direct_trading_available boolean default true,
  fractional_allowed boolean default false, scalable_compatible boolean default true,
  preferred_venue text default 'EIX/gettex', manual_spread_estimate_percent numeric, liquidity_score numeric,
  quality_score numeric, momentum_score numeric, valuation_score numeric, cost_score numeric,
  portfolio_fit_score numeric, risk_control_score numeric, total_score numeric,
  data_source text, source_url text, data_confidence text, last_updated timestamptz, notes text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);

create table if not exists public.savings_plans (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  instrument text, isin text, current_plan_eur numeric default 0,
  new_plan_eur numeric default 0, action text, reason text, score numeric,
  updated_at timestamptz not null default now()
);

create table if not exists public.valuation_snapshots (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  snapshot_date date not null default current_date, timestamp timestamptz not null default now(),
  total_value_eur numeric default 0, cash_eur numeric default 0, invested_value_eur numeric default 0,
  unrealized_pl_eur numeric default 0, daily_gain_eur numeric, daily_gain_percent numeric,
  weekly_gain_eur numeric, weekly_gain_percent numeric, monthly_gain_eur numeric,
  monthly_gain_percent numeric, yearly_gain_eur numeric, yearly_gain_percent numeric,
  unique (user_id, snapshot_date)
);

create table if not exists public.recommendations (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  created_at timestamptz not null default now(), action text, purpose text,
  instrument text, isin text, ticker_id text, quantity numeric,
  estimated_value_eur numeric, fee_issue text, score numeric,
  data_confidence text, reason text, execution_order integer
);

create table if not exists public.app_settings (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  setting_key text not null, setting_value jsonb,
  updated_at timestamptz not null default now(), unique (user_id, setting_key)
);

-- Additive migrations make this script safe to rerun for an existing deployment.
alter table public.holdings
  add column if not exists valuation_ready boolean default false,
  add column if not exists recommendation_ready boolean default false,
  add column if not exists valuation_review_reasons text,
  add column if not exists recommendation_review_reasons text,
  add column if not exists provider_status jsonb,
  add column if not exists enrichment_audit jsonb,
  add column if not exists web_scrape_status text,
  add column if not exists web_scrape_last_run timestamptz,
  add column if not exists web_scrape_sources jsonb,
  add column if not exists web_scrape_confidence text,
  add column if not exists factsheet_url text,
  add column if not exists kid_url text,
  add column if not exists issuer text,
  add column if not exists metadata_conflicts jsonb,
  add column if not exists enrichment_suggestions jsonb,
  add column if not exists confirmed_by_user boolean default false,
  add column if not exists suggested_price_symbols jsonb,
  add column if not exists suggested_asset_type text,
  add column if not exists suggested_category text,
  add column if not exists manual_review_attempted boolean default false,
  add column if not exists last_auto_repair_at timestamptz,
  add column if not exists wkn text,
  add column if not exists current_price_eur numeric,
  add column if not exists buy_in_price_eur numeric,
  add column if not exists sell_price_eur numeric,
  add column if not exists buy_price_eur numeric,
  add column if not exists spread_eur numeric,
  add column if not exists spread_percent numeric,
  add column if not exists screenshot_path text,
  add column if not exists screenshot_captured_at timestamptz,
  add column if not exists source text,
  add column if not exists user_confirmed boolean default false,
  add column if not exists ter_percent numeric,
  add column if not exists fund_size_eur numeric,
  add column if not exists replication_method text,
  add column if not exists distribution_policy text,
  add column if not exists domicile text,
  add column if not exists manual_spread_estimate_percent numeric,
  add column if not exists last_updated timestamptz,
  add column if not exists data_source text,
  add column if not exists source_url text,
  add column if not exists data_confidence text,
  add column if not exists exchange text,
  add column if not exists resolved_price_symbol text;

alter table public.candidate_assets
  add column if not exists valuation_ready boolean default false,
  add column if not exists recommendation_ready boolean default false,
  add column if not exists valuation_review_reasons text,
  add column if not exists recommendation_review_reasons text,
  add column if not exists provider_status jsonb,
  add column if not exists enrichment_audit jsonb,
  add column if not exists web_scrape_status text,
  add column if not exists web_scrape_last_run timestamptz,
  add column if not exists web_scrape_sources jsonb,
  add column if not exists web_scrape_confidence text,
  add column if not exists factsheet_url text,
  add column if not exists kid_url text,
  add column if not exists issuer text,
  add column if not exists metadata_conflicts jsonb,
  add column if not exists enrichment_suggestions jsonb,
  add column if not exists confirmed_by_user boolean default false,
  add column if not exists suggested_price_symbols jsonb,
  add column if not exists suggested_asset_type text,
  add column if not exists suggested_category text,
  add column if not exists manual_review_attempted boolean default false,
  add column if not exists last_auto_repair_at timestamptz,
  add column if not exists wkn text,
  add column if not exists exchange text,
  add column if not exists last_updated_date text,
  add column if not exists resolved_price_symbol text;

alter table public.savings_plans
  add column if not exists category text,
  add column if not exists priority integer,
  add column if not exists user_approved boolean default false,
  add column if not exists last_updated timestamptz default now();

create table if not exists public.market_news (
  id uuid primary key default gen_random_uuid(), user_id text not null, title text, url text,
  source text, published_at timestamptz, summary text, category text, related_symbols jsonb,
  related_themes jsonb, sentiment text, sentiment_score numeric, confidence text,
  fetched_at timestamptz default now()
);

create table if not exists public.strategy_snapshots (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  created_at timestamptz default now(), strategy_name text, market_regime text, risk_profile text,
  target_allocations jsonb, preferred_themes jsonb, reduced_themes jsonb,
  savings_plan_priorities jsonb, rebalance_rules jsonb, current_risks jsonb,
  overweight_underweight_plan text, reasoning text, confidence text
);

alter table public.strategy_snapshots
  add column if not exists current_risks jsonb,
  add column if not exists overweight_underweight_plan text;

create table if not exists public.rebalance_runs (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  created_at timestamptz default now(), run_status text, strategy_snapshot jsonb,
  valuation_snapshot jsonb, recommendations jsonb, savings_plan_changes jsonb,
  news_inputs jsonb, sentiment_summary jsonb, warnings jsonb
);

create table if not exists public.symbol_resolution_cache (
  id uuid primary key default gen_random_uuid(), user_id text not null, asset_key text not null,
  isin text, instrument text, chosen_symbol text, candidate_symbols jsonb, bad_symbols jsonb,
  confidence text, source text, last_tested timestamptz, error text,
  unique (user_id, asset_key)
);

create table if not exists public.data_source_audit (
  id uuid primary key default gen_random_uuid(), user_id text not null, asset_key text, isin text,
  field_name text, field_value text, provider text, source_url text, source_title text,
  fetched_at timestamptz default now(), confidence text, extraction_method text,
  user_confirmed boolean default false, conflict jsonb
);

create table if not exists public.provider_failures (
  id uuid primary key default gen_random_uuid(), user_id text, provider text, asset_key text, isin text,
  attempted_value text, error_type text, error_message text, created_at timestamptz default now(),
  retry_after timestamptz, attempts integer default 1
);

create table if not exists public.enrichment_jobs (
  id uuid primary key default gen_random_uuid(), user_id text, job_type text, status text,
  total_assets integer, processed_assets integer, current_asset text, warnings jsonb,
  completed_keys jsonb, started_at timestamptz default now(), updated_at timestamptz default now(),
  completed_at timestamptz
);

create table if not exists public.market_data_cache (
  id uuid primary key default gen_random_uuid(), user_id text not null, cache_key text not null,
  provider text, data_kind text, payload jsonb, fetched_at timestamptz default now(), expires_at timestamptz,
  unique (user_id, cache_key)
);

-- Additive guards for deployments that created an earlier version of these tables.
alter table public.symbol_resolution_cache
  add column if not exists candidate_symbols jsonb,
  add column if not exists bad_symbols jsonb,
  add column if not exists confidence text,
  add column if not exists source text,
  add column if not exists last_tested timestamptz,
  add column if not exists error text,
  add column if not exists alpha_vantage_symbol text,
  add column if not exists alpha_vantage_candidates jsonb,
  add column if not exists alpha_vantage_error text,
  add column if not exists alpha_vantage_symbol_confidence text,
  add column if not exists alpha_vantage_last_tested timestamptz;

alter table public.holdings
  add column if not exists alpha_vantage_symbol text,
  add column if not exists alpha_vantage_last_price numeric,
  add column if not exists alpha_vantage_previous_close numeric,
  add column if not exists alpha_vantage_currency text,
  add column if not exists alpha_vantage_last_updated timestamptz,
  add column if not exists alpha_vantage_confidence text;

alter table public.candidate_assets
  add column if not exists alpha_vantage_symbol text,
  add column if not exists alpha_vantage_last_price numeric,
  add column if not exists alpha_vantage_previous_close numeric,
  add column if not exists alpha_vantage_currency text,
  add column if not exists alpha_vantage_last_updated timestamptz,
  add column if not exists alpha_vantage_confidence text;

alter table public.data_source_audit
  add column if not exists source_url text,
  add column if not exists source_title text,
  add column if not exists fetched_at timestamptz default now(),
  add column if not exists confidence text,
  add column if not exists extraction_method text,
  add column if not exists user_confirmed boolean default false,
  add column if not exists conflict jsonb;

alter table public.provider_failures
  add column if not exists error_type text,
  add column if not exists error_message text,
  add column if not exists retry_after timestamptz,
  add column if not exists attempts integer default 1;

alter table public.enrichment_jobs
  add column if not exists warnings jsonb,
  add column if not exists completed_keys jsonb,
  add column if not exists updated_at timestamptz default now(),
  add column if not exists completed_at timestamptz;

alter table public.market_data_cache
  add column if not exists provider text,
  add column if not exists data_kind text,
  add column if not exists payload jsonb,
  add column if not exists fetched_at timestamptz default now(),
  add column if not exists expires_at timestamptz;

create table if not exists public.rebalancer_rulebook_versions (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  version_name text, created_at timestamptz default now(), rulebook jsonb,
  confirmed_baseline jsonb, active boolean default false
);

create table if not exists public.rebalance_guardrail_checks (
  id uuid primary key default gen_random_uuid(), user_id text not null,
  rebalance_run_id uuid, created_at timestamptz default now(),
  check_name text, passed boolean, notes text
);

create index if not exists holdings_user_idx on public.holdings(user_id);
create index if not exists candidates_user_idx on public.candidate_assets(user_id);
create index if not exists savings_user_idx on public.savings_plans(user_id);
create index if not exists snapshots_user_date_idx on public.valuation_snapshots(user_id, snapshot_date);
create index if not exists recommendations_user_idx on public.recommendations(user_id, created_at desc);
create index if not exists app_settings_user_idx on public.app_settings(user_id);
create index if not exists market_news_user_time_idx on public.market_news(user_id, published_at desc);
create index if not exists strategy_user_time_idx on public.strategy_snapshots(user_id, created_at desc);
create index if not exists rebalance_user_time_idx on public.rebalance_runs(user_id, created_at desc);
create index if not exists symbol_cache_user_idx on public.symbol_resolution_cache(user_id, last_tested desc);
create index if not exists source_audit_user_idx on public.data_source_audit(user_id, fetched_at desc);
create index if not exists provider_failures_user_idx on public.provider_failures(user_id, created_at desc);
create index if not exists enrichment_jobs_user_idx on public.enrichment_jobs(user_id, updated_at desc);
create index if not exists market_cache_user_idx on public.market_data_cache(user_id, expires_at);
create index if not exists rulebook_versions_user_idx on public.rebalancer_rulebook_versions(user_id, created_at desc);
create index if not exists guardrail_checks_user_idx on public.rebalance_guardrail_checks(user_id, created_at desc);
create unique index if not exists symbol_cache_user_asset_uidx
  on public.symbol_resolution_cache(user_id, asset_key);
create unique index if not exists market_cache_user_key_uidx
  on public.market_data_cache(user_id, cache_key);

alter table public.holdings enable row level security;
alter table public.candidate_assets enable row level security;
alter table public.savings_plans enable row level security;
alter table public.valuation_snapshots enable row level security;
alter table public.recommendations enable row level security;
alter table public.app_settings enable row level security;
alter table public.market_news enable row level security;
alter table public.strategy_snapshots enable row level security;
alter table public.rebalance_runs enable row level security;
alter table public.symbol_resolution_cache enable row level security;
alter table public.data_source_audit enable row level security;
alter table public.provider_failures enable row level security;
alter table public.enrichment_jobs enable row level security;
alter table public.market_data_cache enable row level security;
alter table public.rebalancer_rulebook_versions enable row level security;
alter table public.rebalance_guardrail_checks enable row level security;

create or replace function public.request_user_id()
returns text language sql stable as $$
  select coalesce((coalesce(nullif(current_setting('request.headers', true), ''), '{}')::jsonb ->> 'x-user-id'), '');
$$;

do $$
declare table_name text;
begin
  foreach table_name in array array['holdings','candidate_assets','savings_plans',
    'valuation_snapshots','recommendations','app_settings','market_news','strategy_snapshots','rebalance_runs',
    'symbol_resolution_cache','data_source_audit','provider_failures','enrichment_jobs','market_data_cache',
    'rebalancer_rulebook_versions','rebalance_guardrail_checks']
  loop
    execute format('drop policy if exists streamlit_mvp_access on public.%I', table_name);
    execute format(
      'create policy streamlit_mvp_access on public.%I for all to anon using (user_id = public.request_user_id()) with check (user_id = public.request_user_id())',
      table_name
    );
  end loop;
end $$;

insert into storage.buckets (id, name, public)
values ('holdings-screenshots', 'holdings-screenshots', false)
on conflict (id) do update set public = false;

drop policy if exists streamlit_screenshot_insert on storage.objects;
drop policy if exists streamlit_screenshot_select on storage.objects;
drop policy if exists streamlit_screenshot_delete on storage.objects;
create policy streamlit_screenshot_insert on storage.objects for insert to anon
  with check (bucket_id = 'holdings-screenshots' and (storage.foldername(name))[1] = public.request_user_id());
create policy streamlit_screenshot_select on storage.objects for select to anon
  using (bucket_id = 'holdings-screenshots' and (storage.foldername(name))[1] = public.request_user_id());
create policy streamlit_screenshot_delete on storage.objects for delete to anon
  using (bucket_id = 'holdings-screenshots' and (storage.foldername(name))[1] = public.request_user_id());
