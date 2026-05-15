# 5 things the curve told me this week — with the screens

*A Macro Manv launch post. Below: the actual views I use every morning,
each one screenshotted from the dashboard I've been building. They're all
free to look at. The paid tier — Pro — opens this Friday.*

---

For the last few months I've been quietly building a rates dashboard
alongside the writing. Not a product, not a side hustle — a tool I needed
because my old setup was three browser tabs, a spreadsheet, and a Bloomberg
session I don't always have access to.

This week the curves moved enough that the tools earned their keep. So
this post is half market read, half what-I-built tour. Five screens, five
things the data is saying.

---

## 1. The belly is rich, the wings are cheap

> **Screen: Scanner — top 5 by Sharpe**

The full RV scanner ranks every receive/pay outright, curve, and fly
across the US curve by Sharpe ratio, z-score against 1-year history, and
expected return per year. The top of the screen is receive flies — five
of them, all with Sharpe ≥ +0.50.

| # | Trade | Sharpe | Z | E[Ret] |
|---|---|---:|---:|---:|
| 1 | Receive 3Y5Y30Y fly | +0.57 | +1.38 | +12 bps/yr |
| 2 | Receive 2Y5Y30Y fly | +0.56 | −1.96 | +18 bps/yr |
| 3 | Receive 3Y5Y20Y fly | +0.53 | +0.70 | +10 bps/yr |
| 4 | Receive 2Y5Y20Y fly | +0.50 | −2.09 | +16 bps/yr |
| 5 | Receive 7Y10Y30Y fly | +0.50 | +0.28 | +8 bps/yr |

The pattern: every top pick is a fly with a 5Y belly and a long-end wing.
Translation — **the curve is mispricing belly convexity vs the wings**.
The 5Y has run rich (z = +2.56 vs 1Y history, more on that below) and the
flies are the cleanest way to fade it without naked outright exposure.

The two with negative z scores (rows 2 and 4) are the highest-conviction —
high Sharpe AND a 1-year dislocation pointing the same way. Those are the
ones I'd actually put on.

---

## 2. The 5Y / 7Y curve is screaming

> **Screen: Z-extremes — the trades the model says are stretched**

**Cheap (Z < −2):**
- 5Y / 7Y curve (z = −2.86) — the flattest it's been in a year
- 5Y10Y20Y fly (z = −2.85)
- 20Y / 30Y curve (z = −2.80) — the flattest in 1Y

**Rich (Z > +2):**
- 2Y (z = +2.67)
- 5Y (z = +2.56)
- 3Y (z = +2.53)

When the front end has run this rich AND the 5/7 curve has flattened this
hard, mean reversion says: the front is going to back off, or the belly is
going to lead a steepening. Either way, **pay 5/7 steepener** is the
cleanest expression — it pays you if either leg of the dislocation
normalises.

This is one trade I'd put on conviction-sized. Carry isn't a headwind
(the curve is flat-to-positive in the belly), and you don't need a big
move to make money — going from z = −2.86 to z = −1 unwinds half the
PnL right there.

---

## 3. Regime is "carry > convexity" — and that matters

> **Screen: Regime detector — K-means + conditional Sharpe**

The regime page clusters the last 5 years of rates / vol / credit state
into regimes, then tells you which strategies have worked **conditional
on the current regime** vs unconditional.

We're in a "moderate carry, low convexity premium" regime right now.
In this regime, the historical Sharpe heatmap says:

- **Outright receives**: median Sharpe in regime = +0.31, vs unconditional +0.08
- **Receiver flies**: median Sharpe in regime = +0.42, vs unconditional +0.19
- **Steepeners**: median Sharpe in regime = −0.11, vs unconditional +0.04

So the model says: **receive everything, fade steepeners.** Which lines up
with what the scanner is showing (top picks are all receivers).

This is the kind of read you can't get from a static yield curve chart —
you need the conditional history to see it.

---

## 4. The 30Y JGB is doing something we haven't seen since the 90s

> **Screen: Global Sovereign Curves — Japan section**

The 30Y JGB closed today at **3.85%**. The 40Y at 3.87%. Japan's long-end
is now trading at levels last seen in the early 2000s. The whole JGB curve
is steeper than it's been in two decades.

For rates people: this isn't just a Japan story. **The marginal global
buyer of US duration is Japanese.** Life insurers, GPIF, mega-banks —
their hedged-into-yen US Treasury yield is now negative for the first
time in a long stretch. If they keep repatriating, US long-end demand
weakens. If they hedge less aggressively, US duration becomes a
yen-funded vol trade.

This is the macro story underneath the scanner picks. The 5Y running rich
and the long-end wings staying cheap is *consistent* with weakening
foreign duration demand at the long end. Belly convexity holds up; the
wings get steeper.

---

## 5. Trade of the Week — and the running scoreboard

> **Screen: Trade of the Week + Performance**

Every Monday I publish one rates trade on the record: thesis, entry
level, target, and **the PnL gets tracked from the moment it's posted**.
No after-the-fact editing. Past picks live in a table below the current
one with bps PnL marked to today's close.

This is the part of the dashboard I'm most pleased with — because it's
the part that holds *me* accountable. If the scanner's screens don't
translate into trades that work, you'll see it. If they do, you'll
see that too.

The first Trade of the Week goes live Monday. The thesis I'm leaning
toward — given everything above — is the **pay 5Y/7Y steepener** from
section 2. Entry, target, and the running PnL chart will all be on the
TotW page.

---

## What I built (and why some of it is paid)

Everything you saw above — yield curves, the global section with JGB,
the Trade of the Week page — is **free**. Forever. 22 dashboard pages
including the morning briefing, real rates, breakevens, FX, credit
spreads, cross-asset, and the trade-of-week tracker.

What's paid:

- **Substack tier ($15/mo)**: paid newsletter + 7 semi-pro pages
  (regression, PCA, correlation, watchlist, auctions, CTA positioning).
- **Pro tier ($49/mo)**: everything above PLUS the scanner, the
  DV01-neutral trade builder with copy-paste tickets, the backtester
  (5Y daily PnL/Sharpe/drawdown per trade), the regime detector with
  conditional Sharpe heatmap, the PCA backtest, and the vol surface.
- **Founding tier ($29/mo, first 100 only)**: same access as Pro,
  price locked for life (10-year guarantee), direct line to me. After
  the 100th seat the rate goes to $49 for new joiners.

The whole product opens **this Friday**. If you've been reading the
newsletter and the screens above are speaking your language, the
Founding seat is for you.

---

**Free tier:** [app.macromanv.com](https://app.macromanv.com)
*(or whatever the launch URL ends up being — I'll update this line)*

**Pro / Founding signup:** opens Friday. Reply to this email and I'll
hold a Founding seat for you.

— Manv

*P.S. Everything in this post — the scanner ranking, the z-extremes, the
regime classification, the JGB curve — was pulled live from the dashboard
as I wrote. None of it is hardcoded. The screens you see are the screens
I'm looking at. That's the whole point.*
