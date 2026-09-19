# Local runtime

`SessionRuntime` owns the observer loop, bounded sampling cadence, pipeline
errors, and runtime health counters. It stops the observer in a `finally` block
and never turns a missing frame or analyzer failure into fabricated evidence.
The current daemon IPC is operational for lifecycle health; full daemon-owned
session orchestration remains the next macOS integration step.
