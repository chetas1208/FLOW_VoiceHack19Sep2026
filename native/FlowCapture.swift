// FlowCapture — a small ScreenCaptureKit helper for FLOW.
//
// Why native: ScreenCaptureKit lets us build a content filter that excludes
// chosen applications *at the compositor level*. Pixels belonging to an excluded
// app (1Password, Messages, …) are never rendered into the captured image, so
// they cannot leak into a model prompt even in principle. A `screencapture`-based
// fallback would capture everything and filter afterwards, which is weaker.
//
// Commands:
//   FlowCapture permission            -> {"permission":"granted"|"denied"}
//   FlowCapture request-permission    -> triggers the system prompt once
//   FlowCapture frontmost             -> {"app":"…","bundleId":"…"}
//   FlowCapture capture --out P [--exclude "A,B"] [--max-width N] [--quality Q]
//                                     -> {"ok":true,"path":"…","width":…,"height":…,"excluded":[…]}
//
// Every command prints a single line of JSON on stdout. Errors print
// {"ok":false,"error":"…"} and exit non-zero.

import Foundation
import CoreGraphics
import AppKit
import ScreenCaptureKit
import UniformTypeIdentifiers

struct CLIError: Error { let message: String }

/// Tiny mutex-guarded box so the async capture task can hand an exit status
/// back to the blocked main thread without a data race.
final class Locked: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Int32
    init(_ initial: Int32) { value = initial }
    func set(_ next: Int32) { lock.lock(); value = next; lock.unlock() }
    func get() -> Int32 { lock.lock(); defer { lock.unlock() }; return value }
}

func emit(_ object: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
       let text = String(data: data, encoding: .utf8) {
        print(text)
    }
}

func fail(_ message: String) -> Never {
    emit(["ok": false, "error": message])
    exit(1)
}

func argValue(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: "--\(name)"), i + 1 < args.count else { return nil }
    return args[i + 1]
}

/// Screen Recording permission is a TCC grant; we never try to work around it.
func hasPermission() -> Bool { CGPreflightScreenCaptureAccess() }

func writeJPEG(_ image: CGImage, to path: String, quality: Double) throws {
    let url = URL(fileURLWithPath: path)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
        throw CLIError(message: "could not create image destination at \(path)")
    }
    CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
    guard CGImageDestinationFinalize(dest) else { throw CLIError(message: "could not encode JPEG") }
    // Screenshots may briefly contain work content: keep them owner-only on disk.
    try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
}

func capture() async throws {
    guard hasPermission() else { throw CLIError(message: "screen-recording-permission-denied") }
    guard let out = argValue("out") else { throw CLIError(message: "--out is required") }

    let excludeNames = (argValue("exclude") ?? "")
        .split(separator: ",")
        .map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
        .filter { !$0.isEmpty }
    let maxWidth = Int(argValue("max-width") ?? "1280") ?? 1280
    let quality = Double(argValue("quality") ?? "0.6") ?? 0.6

    let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
    guard let display = content.displays.first else { throw CLIError(message: "no-display-available") }

    // Exclude by application name OR bundle identifier, matched loosely so that
    // "Messages" also catches "Messages.app" and localized variants.
    let excludedApps = content.applications.filter { app in
        let name = app.applicationName.lowercased()
        let bundle = app.bundleIdentifier.lowercased()
        return excludeNames.contains { name == $0 || name.contains($0) || bundle.contains($0) }
    }

    let filter = SCContentFilter(display: display, excludingApplications: excludedApps, exceptingWindows: [])

    let config = SCStreamConfiguration()
    let scale = min(1.0, Double(maxWidth) / Double(display.width))
    config.width = max(320, Int(Double(display.width) * scale))
    config.height = max(240, Int(Double(display.height) * scale))
    config.showsCursor = false
    config.capturesAudio = false
    config.scalesToFit = true

    let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
    try writeJPEG(image, to: out, quality: quality)

    emit([
        "ok": true,
        "path": out,
        "width": image.width,
        "height": image.height,
        "excluded": excludedApps.map { $0.applicationName },
        "display": display.displayID,
    ])
}

let command = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "help"

switch command {
case "permission":
    emit(["ok": true, "permission": hasPermission() ? "granted" : "denied"])

case "request-permission":
    // Presents the system dialog the first time; afterwards macOS requires the
    // user to change it in System Settings › Privacy & Security › Screen Recording.
    let granted = CGRequestScreenCaptureAccess()
    emit(["ok": true, "permission": granted ? "granted" : "denied"])

case "frontmost":
    if let app = NSWorkspace.shared.frontmostApplication {
        emit(["ok": true, "app": app.localizedName ?? "", "bundleId": app.bundleIdentifier ?? ""])
    } else {
        fail("no-frontmost-application")
    }

case "capture":
    // Run the async capture on a task and block the main thread until it settles,
    // recording the exit status so the process code is deterministic (no race
    // between the task calling exit() and main falling off the end).
    let sem = DispatchSemaphore(value: 0)
    let status = Locked(0)
    Task {
        do {
            try await capture()
        } catch let e as CLIError {
            emit(["ok": false, "error": e.message])
            status.set(1)
        } catch {
            emit(["ok": false, "error": "\(error)"])
            status.set(1)
        }
        sem.signal()
    }
    sem.wait()
    exit(status.get())

default:
    emit(["ok": false, "error": "unknown-command", "usage": "permission | request-permission | frontmost | capture --out PATH [--exclude \"A,B\"] [--max-width N] [--quality Q]"])
    exit(2)
}
