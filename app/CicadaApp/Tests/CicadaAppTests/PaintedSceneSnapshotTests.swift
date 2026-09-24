import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// C10 — every framing phase B builds on (`.fullBleed` for the Welcome, `.pane(…)` for the split pages) and Home's
/// band, rendered in every scene. `CICADA_WRITE_SCENES=1 swift test --filter PaintedSceneSnapshotTests` writes each
/// render (and a 50 % day/afternoon/night crossfade per framing) to `$TMPDIR/cicada-scenes` for a person to look at —
/// the `SkyBandTests` convention.
@MainActor
final class PaintedSceneSnapshotTests: XCTestCase {
    static let framings: [(SceneFraming, CGSize)] = [
        (.hero(band: 208), CGSize(width: 1384, height: 208)),
        (.fullBleed, CGSize(width: 1440, height: 900)),
    ] + PaneFraming.allCases.map { (SceneFraming.pane($0), CGSize(width: 540, height: 900)) }

    /// A file-name slug per framing, so the written renders sort and open cleanly.
    private static func slug(_ framing: SceneFraming) -> String {
        switch framing {
        case .hero: "band"
        case .fullBleed: "full-bleed"
        case .pane(let f): "pane-\(f.rawValue)"
        }
    }

    private func render(_ framing: SceneFraming, _ size: CGSize, _ time: SceneTime,
                        t: TimeInterval = 1_000, profile: SceneProfile = .full) throws -> NSBitmapImageRep {
        let renderer = ImageRenderer(content: PaintedSceneFrame(framing: framing, time: time, t: t, profile: profile)
            .frame(width: size.width, height: size.height))
        renderer.scale = 1
        return NSBitmapImageRep(cgImage: try XCTUnwrap(renderer.cgImage, "\(framing) \(time) rendered nothing"))
    }

    /// Mean and spread of luminance over a 24 × 24 grid.
    private static func luminance(_ rep: NSBitmapImageRep) -> (mean: Double, spread: Double) {
        var values: [Double] = []
        for i in 0..<24 {
            for j in 0..<24 {
                guard let c = rep.colorAt(x: (rep.pixelsWide - 1) * i / 23, y: (rep.pixelsHigh - 1) * j / 23)?
                    .usingColorSpace(.sRGB) else { continue }
                values.append(0.2126 * c.redComponent + 0.7152 * c.greenComponent + 0.0722 * c.blueComponent)
            }
        }
        let mean = values.reduce(0, +) / Double(max(values.count, 1))
        let spread = (values.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(max(values.count, 1))).squareRoot()
        return (mean, spread)
    }

    func testEveryFramingRendersEveryScene() throws {
        for (framing, size) in Self.framings {
            var mean: [SceneTime: Double] = [:]
            for time in SceneTime.allCases {
                let rep = try render(framing, size, time)
                XCTAssertEqual(rep.pixelsWide, Int(size.width), "\(framing) \(time)")
                XCTAssertEqual(rep.pixelsHigh, Int(size.height), "\(framing) \(time)")
                let l = Self.luminance(rep)
                XCTAssertGreaterThan(l.spread, 0.02, "\(framing) \(time) is a flat fill, not a painting")
                mean[time] = l.mean
            }
            XCTAssertLessThan(mean[.night]!, mean[.day]! - 0.15, "\(framing): night must read as night")
            XCTAssertLessThan(mean[.night]!, mean[.afternoon]! - 0.1, "\(framing)")
        }
    }

    func testTheGentleProfileStillRendersEveryLayer() throws {
        for (framing, size) in Self.framings {
            XCTAssertGreaterThan(Self.luminance(try render(framing, size, .night, profile: .gentle)).spread, 0.02,
                                 "\(framing) gentle")
        }
    }

    /// Reported, and bounded only against a runaway: `ImageRenderer` is a software render, so the live number (R-HO7)
    /// is measured on the installed app, not here.
    func testRenderCostIsReported() throws {
        let start = Date()
        for i in 0..<10 { _ = try render(.hero(band: 208), CGSize(width: 1384, height: 208), .night, t: Double(i)) }
        let perFrame = Date().timeIntervalSince(start) / 10
        print("PaintedSceneFrame .hero(band: 208) software render: \(String(format: "%.1f", perFrame * 1000)) ms")
        XCTAssertLessThan(perFrame, 0.25)
    }

    func test_writeScenesWhenAsked() throws {
        guard ProcessInfo.processInfo.environment["CICADA_WRITE_SCENES"] == "1" else { return }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-scenes")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        for (framing, size) in Self.framings {
            let name = Self.slug(framing)
            for time in SceneTime.allCases {
                try XCTUnwrap(try render(framing, size, time).representation(using: .png, properties: [:]))
                    .write(to: dir.appendingPathComponent("\(name)-\(time.rawValue).png"))
            }
            for (a, b) in [(SceneTime.day, SceneTime.afternoon), (.afternoon, .night)] {
                let renderer = ImageRenderer(content: ZStack {
                    PaintedSceneFrame(framing: framing, time: a, t: 1_000, profile: .full)
                    PaintedSceneFrame(framing: framing, time: b, t: 1_000, profile: .full).opacity(0.5)
                }.frame(width: size.width, height: size.height))
                renderer.scale = 1
                try XCTUnwrap(NSBitmapImageRep(cgImage: try XCTUnwrap(renderer.cgImage))
                    .representation(using: .png, properties: [:]))
                    .write(to: dir.appendingPathComponent("\(name)-fade-\(a.rawValue)-\(b.rawValue).png"))
            }
        }
        print("scene renders: \(dir.path)")
    }
}
