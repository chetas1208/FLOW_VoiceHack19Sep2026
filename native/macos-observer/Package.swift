// Native capture helper boundary. The Python observer launches this only on macOS.
import PackageDescription

let package = Package(
    name: "FLOWMacOSObserver",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "flow-macos-observer", targets: ["FLOWMacOSObserver"])],
    targets: [.executableTarget(name: "FLOWMacOSObserver")]
)
