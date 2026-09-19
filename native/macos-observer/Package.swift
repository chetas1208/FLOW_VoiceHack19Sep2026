// swift-tools-version:5.9
// Native capture helper for FLOW. The Python observer launches this only on macOS.
// Build: scripts/build-macos-helper.sh  (swift build -c release)
import PackageDescription

let package = Package(
    name: "FLOWMacOSObserver",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "flow-macos-observer", targets: ["FLOWMacOSObserver"])],
    targets: [.executableTarget(name: "FLOWMacOSObserver")]
)
