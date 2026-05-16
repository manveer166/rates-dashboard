# What I've been quietly building (preview)

*A soft-launch post. Shows what's coming. No price, no signup link.
If you want a Founding seat when it opens, reply 'IN' and I'll hold one.*

---

The 30Y JGB closed today at **3.85%**. The 40Y at 3.87%. Highest in two
decades. The marginal global buyer of US duration is Japanese — life
insurers, GPIF, mega-banks — and their hedged-into-yen US Treasury yield
just went negative for the first time in years.

I've been writing about rates here for [N months]. What you haven't seen
is the analytical stack I built underneath the writing — because I got
tired of three browser tabs, a spreadsheet, and a Bloomberg session I
don't always have access to.

It's now real. Quiet beta over the next two weeks; Pro tier opens
shortly after. Here's what's in it.

---

## 1. The scanner

> *Screenshot here — Analysis page, scanner table sorted by Sharpe*

Every receive/pay outright, curve, and fly across the US curve, ranked
by Sharpe. Each row shows carry, rolldown, convexity, transaction cost,
expected return, realised vol, current z-score, and 1-week change. The
math is honest — full cash-flow DV01, true second-order convexity
(`½·C·Δy²`), forward-rate carry. Every formula documented on a
Methodology page. **There's no "0.94 Sharpe outright" sleight of hand**
that turns out to be a units bug; long-end Sharpes sit in the 0.1–0.3
zone like they should. The screen surfaces the trades worth looking at,
not the ones that look pretty in the math.

What it's telling me today: receive-belly flies dominate the top of the
Sharpe ranking, but their **convexity contribution is negative** —
short the wings. That's a tradeable signal that doesn't show up on a
naked carry+roll screen.

## 2. The backtester

> *Screenshot here — Backtester page, P&L decomposition with the
> 4-component card and carry path chart*

Pick any trade. Get 5 years of daily P&L decomposed into:
- **Directional** (linear DV01 mark-to-market)
- **Carry** (path-dependent — recomputed every day from that day's curve,
  not just the entry-time snapshot)
- **Convexity** (per-leg ½·C·Δy² on every mark)
- **Transaction cost** (round-trip bid/ask at practitioner-consensus
  widths, charged at entry and exit)

Total Sharpe, hit rate, max drawdown, daily P&L distribution. CSV
export. Toggles to isolate any component.

This is the page where most "Sharpe 1.5 backtests" die. Bake in the
costs and most things compress. The ones that survive are the ones to
size.

## 3. The trade builder

> *Screenshot here — Trade Builder, DV01-neutral ticket output*

Pick a structure (outright / curve / fly), pick tenors, pick direction.
Out comes a DV01-neutral ticket: leg notionals, $-per-bp per leg, the
current spread level, 1Y z-score, mean. Copy-pasteable into your OMS
or risk system. The math behind every number is the same path the
scanner uses, so the numbers reconcile.

## 4. The regime detector

> *Screenshot here — Regime page, with current cluster + conditional
> Sharpe heatmap + (new) transition matrix*

K-means clustering on level / slope / curvature / vol z-score features
across 5 years of history. For each regime, shows which archetype
(carry-heavy outright vs convexity-heavy fly) had positive Sharpe
**conditional on being in that regime**. New: empirical transition
matrix — probability of leaving the current regime in the next N days.

Honestly labelled: this is clustering, not a hidden Markov model. The
Methodology page makes that explicit. But "what's worked in this kind
of market" is a useful frame even when it's a frame, not a forecast.

## 5. Free tier — and what's not paywalled

Twenty-two pages are free and stay free: morning briefing, US/EU/UK/Japan
curves, real rates and breakevens, cross-asset, the Trade of the Week
with PnL tracked from entry, central bank press feeds, a rates calendar,
a glossary. Everything you need for context, every day.

The paid pages are the analytical tools — scanner, backtester, regime,
trade builder, PCA backtest, vol surface, mean-reversion fits. The
working assumption: if you're going to size a position, you should pay
for the tooling. If you just want to read and learn, the free tier is
generous.

---

## On the math

I've spent the last few weeks rebuilding this codebase to make it
**institutionally defensible**. Single source of truth for DV01 and
convexity. Carry decomposed and path-dependent in the backtester.
Transaction costs from practitioner-consensus bid/ask widths.
Mean-reversion fitted via Ornstein-Uhlenbeck on each trade's own
history, not a 50% heuristic.

It's not a Bloomberg replacement. It's not pretending to be. It's a
**research-grade RV analytics stack** that lets a rates writer or a
small fund analyst think clearly about positioning without paying $24k
a year for a terminal.

The full Methodology page lists every formula AND every known
limitation. Not because I'm hiding behind disclaimers — because if
you're going to pay for this, you deserve to know exactly what the
numbers mean and don't mean.

---

## When does it open

**Pro tier opens [DATE — pick after deploy is done].**

There will be 100 Founding seats at $29/mo, price locked for life
(10-year guarantee). After those 100 it goes to $49/mo for everyone.

**If you want a Founding seat, reply 'IN' to this email.** I'm
reserving seats in reply order; nothing to pay until launch day. No
form, no marketing funnel — just hit reply.

---

*Macro Manv is one person writing about rates. Subscribed to the free
newsletter? Stay subscribed — the daily curve commentary and Trade of
the Week stay free forever. The paid stack is for traders who want the
tools. Either is welcome.*

— Manv
