# Synthetic evaluation artifacts

This directory contains aggregate results produced by ARC's isolated batch
evaluator. The default command is:

```powershell
python -m scripts.run_batch_evaluation
```

The tracked `results/latest.json` artifact is generated from the versioned,
fixed-seed 100-case dataset in `arc/evaluation`. It contains aggregate
synthetic evidence only. It contains no operational rows, provider
identifiers, Payment Link URLs, customer data, prompts, or credentials.

Synthetic recovered amounts are controlled evaluation outcomes. They are not
provider-backed revenue and never enter ARC's Test or Live recovery metrics.
