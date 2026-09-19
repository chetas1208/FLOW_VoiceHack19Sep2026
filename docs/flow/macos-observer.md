# macOS observer status

The Python boundary and Swift package are present. The Swift helper currently
discovers ScreenCaptureKit shareable applications and reports structured JSON.
Actual permission-state reporting, frontmost-window selection, display-targeted
SCStream frame delivery, helper restart, and physical macOS verification remain
environment-dependent work. Linux tests intentionally report this capability as
not configured rather than simulating permission or capture success.
