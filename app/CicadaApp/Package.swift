// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "CicadaApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "CicadaApp",
            resources: [.copy("Resources")]
        )
    ]
)
