# Observer

`DesktopObserver` is the platform-neutral interface used by the daemon. The
mock implementation supports deterministic replay tests. On macOS, the adapter
is the boundary for a ScreenCaptureKit helper; on non-macOS hosts it returns an
explicit unsupported error and never pretends to observe a desktop.

`AdaptiveSampler` uses burst intervals after context or drift changes and longer
intervals during stable focus. `CapturedFrame` owns ephemeral pixel bytes and
offers explicit disposal. No frame is put in the offline event queue.
