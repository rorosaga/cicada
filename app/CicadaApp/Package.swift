// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "CicadaApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "CicadaApp",
            resources: [.copy("Resources")],
            // A warning, never an error: an expression slow to type-check here fails on the slower release runner
            // ("unable to type-check this expression in reasonable time", 0.6.0) — split it before it ships.
            swiftSettings: [.unsafeFlags(["-Xfrontend", "-warn-long-expression-type-checking=150"])]
        ),
        .testTarget(
            name: "CicadaAppTests",
            dependencies: ["CicadaApp"],
            resources: [.copy("Fixtures/sprites")]
        )
    ]
)
