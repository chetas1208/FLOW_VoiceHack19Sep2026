// flow-macos-observer: one-shot JSON helper. Every subcommand prints exactly ONE JSON line to
// stdout. `capture --out -` additionally streams exactly `bytes` raw image bytes after that line.
// Pixels are never written anywhere except the --out path (or stdout). Nothing is cached.
//
// Exit codes: 0 ok, 2 usage, 3 permission_denied, 4 unsupported_os, 5 capture_failed,
// 6 display_not_found.
//
// STATUS: IMPLEMENTED_ENVIRONMENT_UNVERIFIED (written on Linux; not compiled or run on macOS yet).
import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit

let helperVersion = "0.1.0"

// MARK: - JSON output

func emit(_ object: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

func orNull(_ value: Any?) -> Any {
    return value ?? NSNull()
}

func fail(_ code: String, _ message: String, exitCode: Int32) -> Never {
    emit(["ok": false, "error": code, "message": message])
    exit(exitCode)
}

// MARK: - Options

struct Options {
    var display = "active"
    var maxDim = 1280
    var format = "jpeg"
    var out = "-"
}

func parseOptions(_ args: [String]) -> Options {
    var options = Options()
    var index = 0
    while index < args.count {
        let flag = args[index]
        guard index + 1 < args.count else { fail("usage", "missing value for \(flag)", exitCode: 2) }
        let value = args[index + 1]
        switch flag {
        case "--display":
            options.display = value
        case "--max-dim":
            guard let parsed = Int(value), parsed >= 64, parsed <= 8192 else {
                fail("usage", "--max-dim must be an integer from 64 to 8192", exitCode: 2)
            }
            options.maxDim = parsed
        case "--format":
            guard value == "jpeg" || value == "png" else { fail("usage", "--format must be jpeg or png", exitCode: 2) }
            options.format = value
        case "--out":
            options.out = value
        default:
            fail("usage", "unknown option \(flag)", exitCode: 2)
        }
        index += 2
    }
    return options
}

// MARK: - Displays

struct DisplayInfo {
    let id: CGDirectDisplayID
    let frame: CGRect
    let isMain: Bool
    let scale: Double
}

func activeDisplays() -> [DisplayInfo] {
    var count: UInt32 = 0
    guard CGGetActiveDisplayList(0, nil, &count) == .success, count > 0 else { return [] }
    var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
    guard CGGetActiveDisplayList(count, &ids, &count) == .success else { return [] }
    let mainID = CGMainDisplayID()
    var result: [DisplayInfo] = []
    for id in ids.prefix(Int(count)) {
        var scale = 1.0
        if let mode = CGDisplayCopyDisplayMode(id), mode.width > 0 {
            scale = Double(mode.pixelWidth) / Double(mode.width)
        }
        result.append(DisplayInfo(id: id, frame: CGDisplayBounds(id), isMain: id == mainID, scale: scale))
    }
    return result
}

func displayJSON(_ display: DisplayInfo) -> [String: Any] {
    return [
        "id": Int(display.id),
        "isMain": display.isMain,
        "scale": display.scale,
        "frame": [
            "x": Double(display.frame.origin.x), "y": Double(display.frame.origin.y),
            "width": Double(display.frame.size.width), "height": Double(display.frame.size.height),
        ],
    ]
}

func displayContaining(_ rect: CGRect, in displays: [DisplayInfo]) -> CGDirectDisplayID? {
    var bestID: CGDirectDisplayID? = nil
    var bestArea: CGFloat = 0
    for display in displays {
        let overlap = display.frame.intersection(rect)
        let area: CGFloat = overlap.isNull ? 0 : overlap.width * overlap.height
        if area > bestArea {
            bestArea = area
            bestID = display.id
        }
    }
    return bestID
}

// MARK: - Frontmost context

struct FrontContext {
    var name: String? = nil
    var bundleID: String? = nil
    var pid: Int32? = nil
    var title: String? = nil
    var displayID: CGDirectDisplayID? = nil
}

@MainActor
func frontmostContext(includeTitle: Bool) -> FrontContext {
    var context = FrontContext()
    guard let app = NSWorkspace.shared.frontmostApplication else { return context }
    context.name = app.localizedName
    context.bundleID = app.bundleIdentifier
    context.pid = app.processIdentifier
    let flags: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let windows = CGWindowListCopyWindowInfo(flags, kCGNullWindowID) as? [[String: Any]] else { return context }
    let displays = activeDisplays()
    // CGWindowListCopyWindowInfo returns windows front to back; take the frontmost normal window.
    for window in windows {
        guard let ownerPID = window[kCGWindowOwnerPID as String] as? Int32, ownerPID == app.processIdentifier,
              let layer = window[kCGWindowLayer as String] as? Int, layer == 0,
              let boundsDict = window[kCGWindowBounds as String] as? [String: Any],
              let bounds = CGRect(dictionaryRepresentation: boundsDict as CFDictionary),
              bounds.width >= 50, bounds.height >= 50 else { continue }
        context.displayID = displayContaining(bounds, in: displays)
        // Window titles are only readable with Screen Recording permission; never guess without it.
        if includeTitle {
            context.title = window[kCGWindowName as String] as? String
        }
        break
    }
    return context
}

// MARK: - Capture

enum HelperError: Error {
    case displayNotFound
    case encodeFailed
}

func opaqueCopy(_ image: CGImage) -> CGImage {
    guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { return image }
    let info = CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
    guard let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: space, bitmapInfo: info) else { return image }
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
    return context.makeImage() ?? image
}

func encode(_ image: CGImage, format: String) -> Data? {
    let type = (format == "png" ? "public.png" : "public.jpeg") as CFString
    let output = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(output as CFMutableData, type, 1, nil) else { return nil }
    let source = format == "png" ? image : opaqueCopy(image)
    let properties: [CFString: Any] = [kCGImageDestinationLossyCompressionQuality: 0.7]
    CGImageDestinationAddImage(destination, source, properties as CFDictionary)
    guard CGImageDestinationFinalize(destination) else { return nil }
    return output as Data
}

@available(macOS 14.0, *)
func captureImage(display: DisplayInfo, maxDim: Int) async throws -> CGImage {
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    guard let target = content.displays.first(where: { $0.displayID == display.id }) else {
        throw HelperError.displayNotFound
    }
    let filter = SCContentFilter(display: target, excludingWindows: [])
    let configuration = SCStreamConfiguration()
    let nativeWidth = Double(target.width) * display.scale
    let nativeHeight = Double(target.height) * display.scale
    let shrink = min(1.0, Double(maxDim) / max(nativeWidth, nativeHeight, 1.0))
    configuration.width = max(1, Int(nativeWidth * shrink))
    configuration.height = max(1, Int(nativeHeight * shrink))
    configuration.showsCursor = false
    return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
}

func resolveDisplay(_ selector: String, activeID: CGDirectDisplayID?, displays: [DisplayInfo]) -> DisplayInfo? {
    switch selector {
    case "main":
        return displays.first(where: { $0.isMain }) ?? displays.first
    case "active":
        if let activeID = activeID, let match = displays.first(where: { $0.id == activeID }) { return match }
        return displays.first(where: { $0.isMain }) ?? displays.first
    default:
        guard let wanted = UInt32(selector) else { return nil }
        return displays.first(where: { $0.id == wanted })
    }
}

@MainActor
func runCapture(_ options: Options) async -> Int32 {
    guard #available(macOS 14.0, *) else {
        fail("unsupported_os", "ScreenCaptureKit screenshots need macOS 14 or newer; use the screencapture fallback",
             exitCode: 4)
    }
    guard CGPreflightScreenCaptureAccess() else {
        fail("permission_denied", "Screen Recording permission is not granted to this process", exitCode: 3)
    }
    let started = Date()
    let displays = activeDisplays()
    let activeID: CGDirectDisplayID? = options.display == "active" ? frontmostContext(includeTitle: false).displayID : nil
    guard let display = resolveDisplay(options.display, activeID: activeID, displays: displays) else {
        fail("display_not_found", "no display matches \(options.display)", exitCode: 6)
    }
    do {
        let image = try await captureImage(display: display, maxDim: options.maxDim)
        guard let data = encode(image, format: options.format) else { throw HelperError.encodeFailed }
        let latency = Int(Date().timeIntervalSince(started) * 1000)
        var report: [String: Any] = [
            "ok": true, "display_id": Int(display.id), "width": image.width, "height": image.height,
            "bytes": data.count, "format": options.format, "latency_ms": latency,
        ]
        if options.out == "-" {
            emit(report)
            FileHandle.standardOutput.write(data)
        } else {
            let attributes: [FileAttributeKey: Any] = [.posixPermissions: 0o600]
            guard FileManager.default.createFile(atPath: options.out, contents: data, attributes: attributes) else {
                fail("capture_failed", "could not write \(options.out)", exitCode: 5)
            }
            report["path"] = options.out
            emit(report)
        }
        return 0
    } catch HelperError.displayNotFound {
        fail("display_not_found", "display \(display.id) is not shareable", exitCode: 6)
    } catch {
        let nsError = error as NSError
        // SCStreamErrorUserDeclined (-3801): the user has not granted Screen Recording.
        if nsError.code == -3801 { fail("permission_denied", nsError.localizedDescription, exitCode: 3) }
        fail("capture_failed", nsError.localizedDescription, exitCode: 5)
    }
}

// MARK: - Dispatch

@MainActor
func run(_ arguments: [String]) async -> Int32 {
    guard let command = arguments.first else { fail("usage", "expected a subcommand", exitCode: 2) }
    let rest = Array(arguments.dropFirst())
    switch command {
    case "version":
        emit(["ok": true, "helper": "flow-macos-observer", "version": helperVersion,
              "os": ProcessInfo.processInfo.operatingSystemVersionString])
        return 0
    case "permission":
        emit(["ok": true, "screen_recording": CGPreflightScreenCaptureAccess() ? "granted" : "denied"])
        return 0
    case "request-permission":
        let granted = CGRequestScreenCaptureAccess()
        emit(["ok": true, "screen_recording": granted ? "granted" : "denied", "requested": true])
        return 0
    case "displays":
        emit(["ok": true, "displays": activeDisplays().map(displayJSON)])
        return 0
    case "context":
        let permitted = CGPreflightScreenCaptureAccess()
        let front = frontmostContext(includeTitle: permitted)
        emit(["ok": true,
              "application": orNull(front.name),
              "bundle_id": orNull(front.bundleID),
              "pid": orNull(front.pid.map { Int($0) }),
              "window_title": orNull(front.title),
              "window_title_available": permitted,
              "display_id": orNull(front.displayID.map { Int($0) })])
        return 0
    case "capture":
        return await runCapture(parseOptions(rest))
    default:
        fail("usage", "unknown subcommand \(command)", exitCode: 2)
    }
}

Task { @MainActor in
    let code = await run(Array(CommandLine.arguments.dropFirst()))
    exit(code)
}
dispatchMain()
