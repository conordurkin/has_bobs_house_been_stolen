# hasbobwakeshousebeenstolen.com

A tiny site that answers one question: has anything new been filed against
Bob's house at the DuPage County Recorder of Deeds since we started checking?

It exists because deed/title fraud (forged transfers filed with the county)
is a real thing scammy cable news ads love to catastrophize, and this gives
a low-drama, always-checkable answer instead of vague anxiety.

**Before anything else:** DuPage County already runs a free, official,
real-time Property Fraud Alert service — sign up at
https://www.propertyfraudalert.com/ILDupage (linked from the county's own
site: https://www.dupagecounty.gov/elected_officials/recorder/property_fraud_alert.php).
It texts/emails/calls the moment something is recorded against the property.
That's the actual safety net. This site is a friendly second check, not a
replacement for it.

## How it works

1. `scraper/check_records.py` uses Playwright to search the DuPage County
   Recorder's public index (https://recorder.dupageco.org/Search.aspx) by
   property address, and collects every recorded document tied to it.
   (An earlier version also cross-checked by owner name, but that search
   path required an extra checkbox interaction that occasionally raced
   and silently returned zero results — dropped for reliability, since
   address search alone already catches anything filed against the
   property, which is what actually matters.)
2. It compares what it finds against `scraper/baseline.json`, a list of
   document numbers that were already confirmed on file (and confirmed
   normal — the original purchase deed, routine mortgages/refinances,
   mortgage releases, one easement declaration) when this project was set
   up on 2026-08-01.
3. Anything found that ISN'T in the baseline is new. If there's anything
   new, the site says "Yes" and lists what showed up (document type + date,
   no address/name repeated). Otherwise it says "No."
4. A GitHub Actions workflow (`.github/workflows/check.yml`) runs this once
   a day, commits the result to `docs/data.json`, and GitHub Pages serves
   `docs/` as the actual site.

If a scrape fails, or the site's markup changes enough that even the known
1999 purchase deed can't be found (a sanity check against a document we
know is always there), the script does **not** report "No" — it preserves
the last known-good result and flags a check error instead, surfaced
quietly on the page.

## Privacy note

GitHub Pages on a free plan requires a public repo. So that a public,
memorably-named repo/domain doesn't broadcast Bob's exact address, it lives
only as GitHub Actions secrets (read at scrape time), never committed to
the repo. `baseline.json` only contains document numbers/dates, which are
already public county data. The frontend speaks generically ("the
property") rather than repeating the address.

## Setup

1. **Add repo secrets** (Settings → Secrets and variables → Actions):
   - `PROPERTY_HOUSE_NUMBER`
   - `PROPERTY_STREET`
   - `PROPERTY_CITY`
2. **Enable GitHub Pages**: Settings → Pages → Source: "Deploy from a
   branch" → branch `main`, folder `/docs`.
3. Once you register hasbobwakeshousebeenstolen.com, point its DNS at
   GitHub Pages (A records to GitHub's IPs, or a CNAME to
   `<you>.github.io`) — `docs/CNAME` is already set up for it, you just
   need to flip on "Enforce HTTPS" in Pages settings once DNS resolves.
4. To run a check manually instead of waiting for the daily schedule, use
   the "Run workflow" button on the Actions tab (workflow_dispatch is
   enabled).

## Running locally

```
pip install -r scraper/requirements.txt
playwright install chromium

export PROPERTY_HOUSE_NUMBER=...
export PROPERTY_STREET=...
export PROPERTY_CITY=...

python scraper/check_records.py
```

Writes/updates `docs/data.json`. Open `docs/index.html` locally (or run
any static file server) to see it rendered.

## If a real new record ever shows up

Check it on the county site (the site links straight there). If it's
legitimate — an actual refinance, a real easement, whatever — add its
document number to `scraper/baseline.json` under `known_document_numbers`
so it stops showing as "new."
