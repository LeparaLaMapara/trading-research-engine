# The discovery machine (November 2026)

Owner's question, 2026-11-01: if a frontier AI lab that cracks hard maths in a weekend were
handed this market and this account, how would it set up, and how would it make profit fast?

## How those labs actually work

Hard maths falls fast for one reason: a **cheap, trustworthy checker**. A proof checker (Lean)
or a numeric test says right or wrong in seconds, so a model can propose millions of
attempts, and every wrong one is thrown away for free. Speed comes from
generate -> check -> keep, at huge volume.

Markets have no proof checker. The only checker is **profit on data the search never saw**,
and that data is scarce: one new day per day. If you let a search look at the checker a
million times, it learns the noise in the checker, not the market. That is why the open-source
trading agents lose money live: they spent their checker.

So a lab would not "predict the market". It would build three things, in this order.

1. **A checker it can trust.** Costs are the real bid and ask, flat before the rollover (no
   financing), and a **vault**: the latest years locked away, opened once per search, every
   opening logged. Then a third stage nobody can fake: paper trades on live quotes from today
   on.
2. **A wide, cheap search room** on the older years only. Everything simple gets tried, all of
   it counted. Width is free because it never touches the vault.
3. **A short list that crosses the vault once.** Ten rules, family-wise correction for ten,
   not for twenty-eight thousand: that is the whole point of a sealed holdout.

And it would pick the problem the account can win. At $79: no speed edge, no inside
information, no capacity worry. What is left is small, repeatable, intraday patterns that big
money ignores because they do not scale. Intraday means no financing and a 0.01-lot stop that
fits the 6% limit. Each day is a new observation, so the forward checker fills quickly.

## The money, honestly

0.01 lot of EURUSD is about $1,100 of currency. A real edge of 2 bps a trade is about
$0.22 a trade, about $55 a year on one rule: large for $79, small in rand. Profit grows by
edge x capital; this machine's job is the edge. Capital is the owner's decision once the
forward stage shows an edge.

## What runs (one counted experiment per search)

| Stage | Data | Module | Counted as |
|---|---|---|---|
| Search room | 2014-2022 hourly bid/ask, 7 majors | `research/e13_search.py` | every rule in N |
| Vault, once | 2023-2026-09 | `research/vault.py` (append-only log) | Holm over the short list |
| Forward paper | live quotes from now | built next, only for vault survivors | mSPRT over the forward list |
| Live | broker | existing engine + signed limits | owner's rule 4 |

First search: E13, every hourly clock window (pre-registration
`docs/programme/E13-hourly-window-search-prereg.md`). If it finds nothing, the next search
moves to events (data releases, month end) or other instruments, the same machine.
</content>
</invoke>
<invoke name="Bash">
<parameter name="command">cd C:/Users/Administrator/Documents/gits/trading-research-engine && python - <<'EOF'
import json
p='docs/programme/register.json'; r=json.load(open(p,encoding='utf-8'))
r['experiments'].append({"id":"E13","kind":"strategy","programme":"P2","trials":None,
 "title":"Every hourly intraday window on 7 FX majors, searched on 2014-2022, short list tested once on a sealed 2023-2026 vault",
 "prereg":"docs/programme/E13-hourly-window-search-prereg.md","result":None,"verdict":None,"summary":None})
json.dump(r,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False); open(p,'a').write('\n')
EOF
grep -n "trials" research/programme.py | head