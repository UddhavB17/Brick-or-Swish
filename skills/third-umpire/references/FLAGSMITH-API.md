# Flagsmith CLI and API used

Everything goes through the official Flagsmith CLI (v2+), `flagsmith api <path>`, which adds the credentials and base URL. No direct HTTP client is needed: `flagsmith api` reaches every endpoint the review uses, including the one write. `--jq` (gojq) projects each response down to the fields the checks read, so the umpire never holds whole payloads. The commands are in `umpire/third_umpire/flagsmith.py`.

## Auth and hosts

- Interactive: `flagsmith login` stores credentials in the OS keychain.
- Headless (CI, agents): `FLAGSMITH_API_KEY=<Master API key>` (Organisation settings, API Keys). For another host the CLI also reads a host-scoped key, for example `FLAGSMITH_API_KEY_FLAGSMITH_EXAMPLE_COM` for `flagsmith.example.com` (dots and colons become underscores).
- Self-hosted or EU: `FLAGSMITH_API_URL=https://flagsmith.example.com` or `--api-url` (the umpire passes it through).
- `flagsmith auth status` exits 0 only when the credentials work. `scripts/preflight` relies on that.

The environment is addressed by its client-side key (the same key the SDK uses); experiments live under it.

## Reads (one review)

| Purpose | Command |
| --- | --- |
| Environment name, id, project | `flagsmith api api/v1/environments/<key>/ --jq '{id, name, api_key, project}'` |
| Metric definitions (event names) | `flagsmith api api/v1/environments/<key>/experiment-metrics/ --jq '[(.results? // .)[] \| {id, name, aggregation, direction, event: .definition.event}]'` |
| Experiments (for `list` and to pick the running one) | `flagsmith api api/v1/environments/<key>/experiments/ --jq '[(.results? // .)[] \| {id, name, status, started_at, feature: .feature.name}]'` |
| Experiment: status, dates, variations, metrics, rollout and split | `flagsmith api api/v1/environments/<key>/experiments/<id>/ --jq '{id, name, status, ..., experiment_rollout: ...}'` |
| Exposures: per-arm time series, identities excluded for seeing both variants | `flagsmith api api/v1/environments/<key>/experiments/<id>/exposures/ --jq '.exposures \| if . == null then null else {as_of, is_final, payload} end'` |
| Results: per-metric `n`, `sum`, `sum_squares`, inference (`lift`, `ci_low`, `ci_high`, `chance_to_win`), `srm_p_value`, conversion time series | `flagsmith api api/v1/environments/<key>/experiments/<id>/results/ --jq '.results \| if . == null then null else {as_of, is_final, payload} end'` |
| Audit log since launch (100 per page, at most 10 pages) | `flagsmith api 'api/v1/projects/<project>/audit/?page_size=100&page=<n>' --jq '{next, results: [.results[] \| {id, created_date, log, related_object_type, related_object_id, environment: (.environment.id // null), author: (.author.email // null)}]}'` |

The full experiment projection is `JQ_EXPERIMENT` in `flagsmith.py`. Exposures and results are computed by Flagsmith in the background. `as_of` is when they were computed, and the umpire measures runtime up to `as_of`, not up to now.

## The one write

After a SHIP verdict and human approval only:

```bash
echo '{"rollout_decision":"variant","rollout_variant":<multivariate option id>}' \
  | flagsmith api api/v1/environments/<key>/experiments/<id>/complete/ -X POST --input -
```

This ends the experiment and makes the winning variation the environment default at 100% (Flagsmith removes the experiment rollout). It isn't reversible from the experiment itself: going back means changing the flag. Before sending it, the umpire re-reads the experiment and refuses if its status, split, rollout or variations moved since the review.

## Quirks the checks account for

- **SRM p-value is often null.** Flagsmith's SRM test compares exposures with the flag's environment-default split. When the experiment sets its own split, those defaults are 0% per variation and the test is skipped, so the dashboard shows no warning. The umpire tests against `experiment_rollout` itself.
- **Identities exposed to both variants** are dropped from results and only counted in `exposures.payload.excluded_identities`, so a broken split can look clean in the results.
- **No inference until each arm has 50 identities and 5 conversions** ("Collecting data"). The umpire then recomputes lift and interval from the raw sums.
- **Audit log** endpoints need a plan that includes audit logs. A 403 there becomes a WARN on the `audit` check, not an error.

## Errors

The CLI prints non-2xx responses to stderr and exits non-zero. The umpire turns that into exit 1 with the status: 401 means bad or missing credentials, 403 means the key lacks permission or the plan lacks the feature, and 404 means a wrong environment key or experiment id.
