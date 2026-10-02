import AppKit
import SwiftUI

/// G166 (DESIGN_RULES §9, 2026-09-30) — a site's mark, drawn like the icon on a browser tab: the site's own favicon at
/// its natural shape, a 4 pt corner on the favicon alone so a square icon does not bleed, never a circle and never a ring around a real icon (an entity's circle is
/// for brands-as-avatars). The favicon comes from Cicada's own API (`GET /reading/sites/{site}/icon`, which asks an icon
/// service; the site itself is never contacted and the app makes no network call of its own). Until it arrives, and
/// for a site that has none: the bundled mark of a known family (LinkedIn, X, …), else a ring monogram — never a solid
/// fill. The bundled mark is drawn bare at the same size (never clipped or altered, DR-52), so the row does not move
/// when the favicon lands.
struct SiteIcon: View {
    let site: String
    var label: String? = nil
    var size: SiteIconLayout.Size = .row
    /// G61 S3-b — the page whose source names this site: its icon is asked of that page's own route.
    var entity: String? = nil
    @Environment(Store.self) private var store
    @State private var image: NSImage?

    var body: some View {
        let side = CicadaTheme.scaled(size.points)
        Group {
            switch SiteIconLayout.rung(favicon: image != nil, site: site) {
            case .favicon:
                // Only a fetched favicon is clipped: a bundled brand mark stands bare (DR-52).
                if let image {
                    Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
                        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.scaled(SiteIconLayout.cornerRadius),
                                                    style: .continuous))
                }
            case .bundled(let name):
                LogoImage(name: name, size: side)
            case .monogram:
                SiteMonogram(letter: SiteMonogram.letter(label ?? site), side: side)
            }
        }
        .frame(width: side, height: side)
        .accessibilityHidden(true)
        .task(id: "\(store.bank)|\(site)|\(entity ?? "")") {
            image = await SiteIconStore.shared.image(site: site, bank: store.bank, entity: entity)
        }
    }
}

/// The pure half of `SiteIcon`: its sizes, its corner, and which rung draws. Tested without a view.
enum SiteIconLayout {
    enum Size: Equatable {
        /// A Settings row's leading mark.
        case row
        /// Inline beside a line of text (the Feed's Read section, Home).
        case inline

        var points: CGFloat { self == .row ? 20 : 16 }
    }

    enum Rung: Equatable {
        case favicon
        case bundled(String)
        case monogram
    }

    /// A small radius, like a tab's icon — never a circle. Applied to a fetched favicon only.
    static let cornerRadius: CGFloat = 4

    /// Whether a rung is clipped to `cornerRadius`: only the favicon. A bundled brand mark stands bare (DR-52) and the
    /// monogram draws its own rounded ring.
    static func clips(_ rung: Rung) -> Bool { rung == .favicon }

    /// The site keys of the families whose mark ships in the app (`Resources/logos`), by the file it draws from.
    static let familyMarks: [String: String] = [
        "linkedin": "linkedin", "x": "x", "instagram": "instagram", "tiktok": "tiktok", "reddit": "reddit",
    ]

    /// The favicon, else the family's bundled mark when one ships, else the monogram.
    static func rung(favicon: Bool, site: String, markExists: (String) -> Bool = LogoImage.exists(name:)) -> Rung {
        if favicon { return .favicon }
        if let name = familyMarks[site.lowercased()], markExists(name) { return .bundled(name) }
        return .monogram
    }
}

/// A hairline ring with the site's first letter — the "no icon" mark (never a solid fill).
struct SiteMonogram: View {
    let letter: String
    let side: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: CicadaTheme.scaled(SiteIconLayout.cornerRadius), style: .continuous)
                .strokeBorder(CicadaTheme.border, lineWidth: 1)
            Text(letter)
                .font(CicadaTheme.font(size: side * 0.55, weight: .medium))
                .foregroundStyle(CicadaTheme.textSecondary)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
        }
        .frame(width: side, height: side)
    }

    /// The first letter or digit of the site's name, uppercased; `?` when there is none. Deterministic.
    static func letter(_ name: String) -> String {
        guard let first = name.first(where: { $0.isLetter || $0.isNumber }) else { return "?" }
        return String(first).uppercased()
    }
}
