# Failure recovery

Analyzer failures become `unknown` observations. Cloud failures leave semantic
events in the bounded offline queue until acknowledged. Uploads use bounded
exponential retry and idempotency keys. Voice is optional and cannot own the
session lifecycle. Observer/runtime errors mark the runtime degraded and stop
the observer cleanly. Native helper restart and daemon checkpoint recovery are
not yet verified on macOS.
