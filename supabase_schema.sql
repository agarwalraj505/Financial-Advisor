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

create index if not exists holdings_user_idx on public.holdings(user_id);
create index if not exists candidates_user_idx on public.candidate_assets(user_id);
create index if not exists savings_user_idx on public.savings_plans(user_id);
create index if not exists snapshots_user_date_idx on public.valuation_snapshots(user_id, snapshot_date);
create index if not exists recommendations_user_idx on public.recommendations(user_id, created_at desc);
create index if not exists app_settings_user_idx on public.app_settings(user_id);

alter table public.holdings enable row level security;
alter table public.candidate_assets enable row level security;
alter table public.savings_plans enable row level security;
alter table public.valuation_snapshots enable row level security;
alter table public.recommendations enable row level security;
alter table public.app_settings enable row level security;

create or replace function public.request_user_id()
returns text language sql stable as $$
  select coalesce((coalesce(nullif(current_setting('request.headers', true), ''), '{}')::jsonb ->> 'x-user-id'), '');
$$;

do $$
declare table_name text;
begin
  foreach table_name in array array['holdings','candidate_assets','savings_plans',
    'valuation_snapshots','recommendations','app_settings']
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
