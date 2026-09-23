import AppKit
import SwiftUI

/// Resolves the file URLs a drop carries, then hands them over on the main actor.
/// One loader for every drop target (the window, an empty state, the panel).
enum IntakeDrop {
    static func load(_ providers: [NSItemProvider], _ completion: @escaping @MainActor ([URL]) -> Void) {
        let group = DispatchGroup()
        let lock = NSLock()
        var urls: [URL] = []
        for provider in providers where provider.canLoadObject(ofClass: URL.self) {
            group.enter()
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url { lock.lock(); urls.append(url); lock.unlock() }
                group.leave()
            }
        }
        group.notify(queue: .main) { MainActor.assumeIsolated { completion(urls) } }
    }
}

/// A chat vendor's real mark (Track L precedence through `OriginIconography`),
/// never recoloured; decorative, so hidden from VoiceOver (the text names it).
struct VendorMark: View {
    let origin: String?
    var size: CGFloat

    init(vendor: ChatVendor, size: CGFloat) { self.origin = vendor.origin; self.size = size }
    init(origin: String?, size: CGFloat) { self.origin = origin; self.size = size }

    var body: some View {
        LogoImage.platformTile(name: origin.flatMap(OriginIconography.logoName(for:)) ?? "",
                               size: size, systemFallback: "bubble.left.and.bubble.right")
            .accessibilityHidden(true)
    }
}

/// What sits over the whole window: the drop veil while a file is dragged over
/// it (I1), and the intake overlay while the router shows it (design §5.1). A
/// ZStack layer, not a `.sheet`, so it can sit above any page and share the veil.
struct IntakeLayer: View {
    let dropTargeted: Bool
    @Environment(IntakeRouter.self) private var intake
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            if intake.isOverlayPresented { IntakeOverlay().transition(.opacity) }
            if dropTargeted { IntakeDropVeil().transition(.opacity) }
        }
        .animation(CicadaMotion.dropVeil(reduceMotion: reduceMotion), value: dropTargeted)
        .animation(CicadaMotion.panel(reduceMotion: reduceMotion), value: intake.isOverlayPresented)
    }
}

struct IntakeDropVeil: View {
    var body: some View {
        ZStack {
            CicadaTheme.scrim.ignoresSafeArea()
            RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .strokeBorder(CicadaTheme.accent, style: StrokeStyle(lineWidth: 2, dash: [8, 6]))
                .padding(CicadaTheme.scaled(12))
            VStack(spacing: CicadaTheme.spacingSM) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ForEach(ChatVendor.allCases) { VendorMark(vendor: $0, size: CicadaTheme.scaled(28)) }
                }
                Text(Copy.intakeVeil).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(CicadaTheme.spacingLG)
            .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.cornerRadius, style: .continuous))
        }
        .allowsHitTesting(false)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Copy.intakeVeil)
    }
}

struct IntakeOverlay: View {
    @Environment(IntakeRouter.self) private var intake

    var body: some View {
        ZStack {
            CicadaTheme.scrim
                .ignoresSafeArea()
                .onTapGesture { intake.dismiss() }
                .accessibilityHidden(true)
            ScrollView {
                IntakePanel(origin: .windowDrop)
                    .padding(CicadaTheme.spacingXL)
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(maxWidth: CicadaTheme.scaled(600), maxHeight: CicadaTheme.scaled(640))
            .fixedSize(horizontal: false, vertical: true)
            .background(CicadaTheme.surface, in: RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: CicadaTheme.radiusLarge, style: .continuous)
                .stroke(CicadaTheme.border, lineWidth: 1))
            .padding(CicadaTheme.spacingXL)
        }
        .onKeyPress(.escape) { intake.dismiss(); return .handled }
    }
}
