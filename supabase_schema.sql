-- Chạy một lần trong Supabase SQL Editor.
-- Mô hình: app local ghi bằng service_role; website bên ngoài chỉ đọc bằng anon.

create table if not exists public.traffic_cache (
  domain text primary key,
  monthly_visits bigint,
  monthly_visits_raw text,
  change text,
  trend text,
  pages_per_visit text,
  avg_duration text,
  bounce_rate text,
  registration text,
  top_regions jsonb,
  top_keywords jsonb,
  status text not null default 'ok',
  fetched_at double precision not null
);

create table if not exists public.brand_site_cache (
  brand text primary key,
  domain text not null,
  fetched_at double precision not null
);

create table if not exists public.projects (
  name text primary key,
  updated_at double precision not null
);

create table if not exists public.project_domains (
  project_name text references public.projects(name) on update cascade on delete cascade,
  domain text references public.traffic_cache(domain) on update cascade on delete cascade,
  primary key (project_name, domain)
);

alter table public.traffic_cache enable row level security;
alter table public.brand_site_cache enable row level security;
alter table public.projects enable row level security;
alter table public.project_domains enable row level security;

-- Website ngoài được tra dữ liệu traffic đã có, nhưng không được sửa/xóa.
drop policy if exists "public read traffic cache" on public.traffic_cache;
create policy "public read traffic cache"
on public.traffic_cache for select
to anon, authenticated
using (status = 'ok');

-- Không tạo policy INSERT/UPDATE/DELETE cho anon.
-- service_role của app local tự động bypass RLS.

grant usage on schema public to anon, authenticated;
grant select on public.traffic_cache to anon, authenticated;
revoke insert, update, delete on public.traffic_cache from anon, authenticated;
revoke all on public.brand_site_cache from anon, authenticated;
revoke all on public.projects from anon, authenticated;
revoke all on public.project_domains from anon, authenticated;
