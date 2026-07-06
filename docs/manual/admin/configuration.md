# Configuration

foragerr reads its configuration from three layers, in precedence order (highest
first):

1. `FORAGERR_*` environment variables
2. `<config_dir>/config.yaml`
3. built-in defaults

The config directory itself is set by the `FORAGERR_CONFIG_DIR` environment variable
(default `/config`) and holds **all** persistent state: the SQLite database, the
config file, logs, backups, and caches. On first run against an empty config
directory, foragerr generates a fully-documented `config.yaml` there — every setting
listed with its default value and an explanatory comment; secret fields are written
only as commented-out placeholders, never with a real value.

Configuration is validated as a whole at startup; an invalid value fails fast with a
field-precise error rather than starting in a partially-broken state. A handful of
interval settings (see table) are clamped into a documented safe range with a warning
instead of failing outright if you set them out of range.

## Settings reference

Source: `backend/src/foragerr/config.py`. Every setting below is read as
`FORAGERR_<NAME>` (uppercased) from the environment, or as the same name (lowercase)
under the top level of `config.yaml`.

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `config_dir` | `FORAGERR_CONFIG_DIR` | `/config` | Environment-only; not read from `config.yaml` itself. |
| `host` | `FORAGERR_HOST` | `0.0.0.0` | Interface the HTTP listener binds to. |
| `port` | `FORAGERR_PORT` | `8789` | TCP port for the HTTP listener. |
| `log_level` | `FORAGERR_LOG_LEVEL` | `INFO` | One of DEBUG/INFO/WARNING/ERROR/CRITICAL. |
| `log_max_bytes` | `FORAGERR_LOG_MAX_BYTES` | `10000000` | Log file size before rotation. |
| `log_backup_count` | `FORAGERR_LOG_BACKUP_COUNT` | `5` | Rotated log files retained. |
| `scheduler_tick_seconds` | `FORAGERR_SCHEDULER_TICK_SECONDS` | `60` | Clamped to 5-60. |
| `http_connect_timeout_seconds` | `FORAGERR_HTTP_CONNECT_TIMEOUT_SECONDS` | `10.0` | Outbound HTTP connect timeout, all clients. |
| `http_read_timeout_seconds` | `FORAGERR_HTTP_READ_TIMEOUT_SECONDS` | `30.0` | Outbound HTTP read timeout. |
| `http_write_timeout_seconds` | `FORAGERR_HTTP_WRITE_TIMEOUT_SECONDS` | `30.0` | Outbound HTTP write timeout. |
| `http_pool_timeout_seconds` | `FORAGERR_HTTP_POOL_TIMEOUT_SECONDS` | `30.0` | Max wait for a pooled outbound connection. |
| `http_max_response_bytes` | `FORAGERR_HTTP_MAX_RESPONSE_BYTES` | `26214400` (25 MiB) | Byte cap on outbound response bodies; callers may lower, never raise. |
| `db_busy_timeout_ms` | `FORAGERR_DB_BUSY_TIMEOUT_MS` | `5000` | SQLite `busy_timeout`, all connections. |
| `db_backup_retention` | `FORAGERR_DB_BACKUP_RETENTION` | `3` | Pre-migration DB backups retained. |
| `workers_search` | `FORAGERR_WORKERS_SEARCH` | `1` | Worker count, "search" workload (keep at 1 for indexer politeness). |
| `workers_download` | `FORAGERR_WORKERS_DOWNLOAD` | `1` | Worker count, "download" workload (SAB tracking + DDL). |
| `workers_pp` | `FORAGERR_WORKERS_PP` | `1` | Worker count, post-processing workload. |
| `workers_default` | `FORAGERR_WORKERS_DEFAULT` | `2` | Worker count, everything unclassified. |
| `shutdown_grace_seconds` | `FORAGERR_SHUTDOWN_GRACE_SECONDS` | `25` | Clamped to 1-29 (must stay under 30s). |
| `job_history_retention_days` | `FORAGERR_JOB_HISTORY_RETENTION_DAYS` | `30` | Days of job history kept before pruning. |
| `usenet_retention_days` | `FORAGERR_USENET_RETENTION_DAYS` | `0` | Global usenet retention; 0 disables. Per-indexer override always wins. |
| `backlog_search_interval_seconds` | `FORAGERR_BACKLOG_SEARCH_INTERVAL_SECONDS` | `21600` (6h) | Minimum 1 hour. |
| `backlog_search_delay_seconds` | `FORAGERR_BACKLOG_SEARCH_DELAY_SECONDS` | `30` | Clamped **up** to a 30s floor if set lower. |
| `comicvine_api_key` | `FORAGERR_COMICVINE_API_KEY` | *(empty, secret)* | See `secrets.md`. |
| `comicvine_base_url` | `FORAGERR_COMICVINE_BASE_URL` | `https://comicvine.gamespot.com/api` | ComicVine API base. Leave at the default; overridden only to point the metadata client at a fixture server (the e2e harness). Egress policy still applies. |
| `comicvine_min_interval_seconds` | `FORAGERR_COMICVINE_MIN_INTERVAL_SECONDS` | `2.0` | Minimum seconds between any two ComicVine requests, process-wide. |
| `comicvine_page_size` | `FORAGERR_COMICVINE_PAGE_SIZE` | `100` | ComicVine's own page-size cap. |
| `comicvine_max_pages` | `FORAGERR_COMICVINE_MAX_PAGES` | `200` | Hard cap on pages walked per list endpoint. |
| `comicvine_search_result_cap` | `FORAGERR_COMICVINE_SEARCH_RESULT_CAP` | `1000` | Series-search candidates cap; truncation is visible. |
| `comicvine_ignored_publishers` | `FORAGERR_COMICVINE_IGNORED_PUBLISHERS` | *(empty)* | Comma-separated, case-insensitive. |
| `comicvine_image_hosts` | `FORAGERR_COMICVINE_IMAGE_HOSTS` | `comicvine.gamespot.com,comicvine1.cbsistatic.com,static.comicvine.com` | Allowlisted cover-image hostnames. |
| `dognzb_api_key` | `FORAGERR_DOGNZB_API_KEY` | *(empty, secret)* | See `secrets.md`. |
| `nzbsu_api_key` | `FORAGERR_NZBSU_API_KEY` | *(empty, secret)* | See `secrets.md`. |
| `sabnzbd_api_key` | `FORAGERR_SABNZBD_API_KEY` | *(empty, secret)* | See `secrets.md`. |
| `track_downloads_interval_seconds` | `FORAGERR_TRACK_DOWNLOADS_INTERVAL_SECONDS` | `60` | Minimum 60s (download pool is serialized). |
| `auto_redownload_failed` | `FORAGERR_AUTO_REDOWNLOAD_FAILED` | `true` | Self-healing re-search after a failed download. |

Unknown keys found in `config.yaml` are ignored with a logged warning rather than
failing startup, so a config file from a slightly different version doesn't brick
the instance.

## Config-file precedence in practice

If you set the same value in both `config.yaml` and its `FORAGERR_*` environment
variable, the environment variable wins — this is deliberate so a Docker Compose
file (env vars) can override a persisted config file without editing it. To change a
setting persistently without an environment variable, edit `config.yaml` under the
config directory and restart.
