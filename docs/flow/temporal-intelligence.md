# Temporal intelligence

`TemporalContext` retains only a bounded recent history, current activity,
last aligned activity, task phase, and drift state. `TaskSegmenter` groups
observations by semantic activity, application/category changes, and long gaps.
Segments are reproducibly derived at report time and contain duration,
alignment, confidence, and observation counts.
