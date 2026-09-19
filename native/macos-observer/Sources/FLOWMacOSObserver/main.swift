import Foundation
import ScreenCaptureKit

// This helper intentionally emits metadata only until the Python bridge asks
// for a frame. ScreenCaptureKit permission and capture remain on-device.
let semaphore = DispatchSemaphore(value: 0)
Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        let apps = content.applications.map { ["name": $0.applicationName, "bundle_id": $0.bundleIdentifier] }
        let data = try JSONSerialization.data(withJSONObject: ["type": "capabilities", "applications": apps])
        FileHandle.standardOutput.write(data + Data([10]))
    } catch {
        let data = try! JSONSerialization.data(withJSONObject: ["type": "error", "error": "screen_capture_unavailable"])
        FileHandle.standardOutput.write(data + Data([10]))
    }
    semaphore.signal()
}
semaphore.wait()
