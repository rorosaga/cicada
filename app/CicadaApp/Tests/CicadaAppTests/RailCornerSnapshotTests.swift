import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-10-07 — the rail and the titlebar band are one frame around a page panel with a rounded top-leading
/// corner. This writes it offscreen, never launching the app: a mock window (the AppKit band as its window colour, mock
/// traffic lights and command bar) holding the real `NavRail` and the real `shellContentPanel()`, in both themes, at 1×
/// and the window's top-left region at 3×. Opt-in: `CICADA_RAIL_CORNER_SNAPSHOTS=<dir> swift test --filter
/// RailCornerSnapshotTests`.
@MainActor
final class RailCornerSnapshotTests: XCTestCase {
    private static let size = CGSize(width: 960, height: 600)
    private static let band: CGFloat = 52
    private static let zoomRegion = CGRect(x: 0, y: 0, width: 220, height: 180)

    func test_writeTheFrameWhenAsked() throws {
        guard let path = ProcessInfo.processInfo.environment["CICADA_RAIL_CORNER_SNAPSHOTS"] else { return }
        let dir = URL(fileURLWithPath: path)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for mode in AppColorScheme.allCases {
            CicadaTheme.mode = mode
            let name = "rail-corner-\(mode.rawValue)"
            try write(window(mode), scale: 1, crop: nil, to: dir.appendingPathComponent("\(name).png"))
            try write(window(mode), scale: 3, crop: Self.zoomRegion, to: dir.appendingPathComponent("\(name)-zoom3x.png"))
        }
        print("rail corner snapshots: \(dir.path)")
    }

    private func window(_ mode: AppColorScheme) -> some View {
        ZStack(alignment: .topLeading) {
            Color(nsColor: CicadaTheme.titlebarBackground(for: mode))
            VStack(spacing: 0) {
                titlebar.frame(height: Self.band)
                HStack(spacing: 0) {
                    NavRail(selectedTab: .constant(.sleep), labelled: false, inboxCount: 3, isSleeping: false,
                            needsAttention: false)
                        .zIndex(1)
                    page.frame(maxWidth: .infinity, maxHeight: .infinity).shellContentPanel()
                }
            }
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(12)
        .background(Color(white: 0.5))
        .environment(AppRouter())
        .environment(\.colorScheme, mode == .dark ? .dark : .light)
    }

    private var titlebar: some View {
        HStack(spacing: 8) {
            ForEach([Color(red: 1, green: 0.37, blue: 0.34), Color(red: 1, green: 0.74, blue: 0.18),
                     Color(red: 0.16, green: 0.78, blue: 0.25)], id: \.self) { Circle().fill($0).frame(width: 12) }
            Image(systemName: "sidebar.left").foregroundStyle(CicadaTheme.textSecondary).padding(.leading, 20)
            Spacer()
            CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgButton)
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                .overlay(alignment: .leading) {
                    Text("Search your memory").foregroundStyle(CicadaTheme.textTertiary).padding(.leading, 12)
                }
                .frame(width: 420, height: 32)
            Spacer()
            Image(systemName: "questionmark.circle").foregroundStyle(CicadaTheme.textSecondary)
        }
        .padding(.horizontal, 20)
    }

    private var page: some View {
        VStack(alignment: .leading, spacing: 20) {
            PageTitle("Sleep Cycle")
            CicadaTheme.shape(CicadaTheme.radiusLarge).fill(CicadaTheme.surface)
                .ringed(in: CicadaTheme.shape(CicadaTheme.radiusLarge))
                .frame(height: 260)
            Text("Details").foregroundStyle(CicadaTheme.textSecondary)
            Spacer()
        }
        .padding(.top, 24)
        .padding(.horizontal, 48)
        .background(CicadaTheme.background)
    }

    private func write(_ view: some View, scale: CGFloat, crop: CGRect?, to url: URL) throws {
        let renderer = ImageRenderer(content: view)
        renderer.scale = scale
        var image = try XCTUnwrap(renderer.cgImage)
        if let crop {
            // The region is in points of the window, which sits 12 pt into the rendered canvas.
            let r = crop.offsetBy(dx: 12, dy: 12)
            image = try XCTUnwrap(image.cropping(to: CGRect(x: r.minX * scale, y: r.minY * scale,
                                                            width: r.width * scale, height: r.height * scale)))
        }
        let rep = NSBitmapImageRep(cgImage: image)
        try XCTUnwrap(rep.representation(using: .png, properties: [:])).write(to: url)
    }
}
