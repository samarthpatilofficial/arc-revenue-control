# ARC Batch Evaluation

## Purpose

ARC's batch evaluation measures recovery control behavior across a diverse
set of revenue-risk cases instead of relying on one selected transaction. It
tests whether ARC identifies value at risk, respects stopping and approval
rules, prevents duplicate or stale actions, and attributes a controlled
synthetic recovery only after an explicit successful synthetic outcome.

## Evidence model

ARC presents two separate evidence classes:

- **Provider-backed proof:** the existing Razorpay Test Mode case proves one
  closed loop using authoritative provider evidence. It is test money, not
  live merchant revenue.
- **Batch proof:** the fixed 100-case evaluation measures control behavior and
  controlled outcomes without writing to Razorpay or operational persistence.

These evidence classes are never combined. Synthetic results do not create
`RecoveryAttribution` rows and do not enter Test Mode or Live Mode dashboard
metrics.

## Dataset

Dataset `arc-synthetic-recovery-v1` uses seed `1403`, a fixed UTC evaluation
clock, INR amounts, and synthetic identifiers only. The 100 cases comprise:

| Scenario family | Cases |
| --- | ---: |
| Already captured | 10 |
| Active platform retry | 10 |
| Customer authentication failure | 12 |
| Insufficient funds | 12 |
| Issuer/bank failure | 10 |
| Gateway/network failure | 10 |
| Retry exhausted | 8 |
| High-value approval | 8 |
| Automated-attempt limit | 5 |
| Contact limit | 5 |
| Hard stopping rule | 4 |
| Incomplete/unknown context | 3 |
| Duplicate action | 2 |
| Stale capture before execution | 1 |

Amounts range across plausible synthetic values. No customer, merchant,
payment, subscription, Payment Link, or provider-payment identifier from the
operational system is used.

## Method

The in-memory runner constructs transient `PaymentCase` objects and reuses the
implemented production boundaries for:

- eligibility and captured/platform-retry protection;
- deterministic failure classification;
- strategy context validation and bounded action compatibility;
- rule-only strategy bypasses;
- merchant-policy parsing, limits, thresholds, stopping rules, and
  authorization;
- the execution idempotency-key algorithm.

The default strategy provider is offline and deterministic. Its fixtures are
validated by the same strict `StrategyOutput` model and action vocabulary as
the OpenAI boundary. No database, OpenAI, or Razorpay request is made. An
optional `--strategy-mode openai --limit N` mode uses the existing strict
OpenAI Responses API client for a bounded subset; it is not required by CI and
still does not access Razorpay or operational persistence.

Each case produces a bounded in-memory decision record covering eligibility,
diagnosis, strategy, policy, execution count, controlled outcome, and final
classification. Aggregate results and scenario breakdowns are tracked; case
identifiers and provider-like data are deliberately excluded from the public
artifact. ARC's operational database audit trail remains separate.

For cases that reach simulated execution, the dataset supplies either an
explicit controlled successful capture or an unresolved outcome. Merely
authorizing or simulating an action never counts as recovery.

## Results

The tracked result was generated with:

```powershell
python -m scripts.run_batch_evaluation
```

| Metric | Result |
| --- | ---: |
| Cases evaluated | 100 |
| Revenue evaluated | ₹452,658.00 |
| Revenue at risk | ₹400,020.00 |
| Eligible cases | 80 |
| Strategy-provider cases | 77 |
| Deterministic bypasses | 23 |
| Automated actions authorized | 35 |
| Human approval required | 8 |
| Wait cases | 30 |
| Safe stops | 28 |
| Already-captured protected | 11 |
| Duplicate actions prevented | 2 |
| Synthetic recovered cases | 21 |
| Synthetic recovered amount | ₹48,442.00 |
| Synthetic recovery rate by amount | 12.1099% |
| Synthetic recovery rate by eligible cases | 26.25% |
| Unresolved eligible cases | 58 |
| Strategy failures/fallbacks | 0 |

All values are calculated from observed per-case behavior. The aggregate
artifact is [evaluation/results/latest.json](../evaluation/results/latest.json).

## Safety results

| Safety invariant | Observed violations |
| --- | ---: |
| Policy violations executed | 0 |
| Unsafe actions after captured truth | 0 |
| Duplicate executions | 0 |

The run passes only when explicit safety and accounting checks succeed. It
fails on unsafe execution, duplicate execution, inconsistent totals, result
count mismatch, mixed evidence classes, or unsafe automation from unknown
context.

## Limitations

- Synthetic outcomes are controlled evaluation outcomes, not observed
  merchant behavior.
- The synthetic recovered amount is **not merchant revenue**.
- Synthetic results never enter provider-backed dashboard metrics.
- Provider-backed proof remains the existing Razorpay Test Mode case.
- Offline evaluation does not imply 100 live OpenAI calls.
- Production causal impact requires a governed merchant deployment and Live
  Mode evidence.
