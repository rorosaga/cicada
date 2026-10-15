import AppKit
import SwiftUI

/// Looks polish (owner, 2026-10-15: "an Aa with the font and the name would be cool, or fonts if several") — the Type
/// section's specimens: one per family the page renders, a large "Aa", the family's name, and where it is used.
///
/// The "Aa" must look like the real font, and the app loads nothing a page names from the web, so it can't fetch the
/// site's web font. The capture draws "Aa" in the page itself, with the page's own loaded face, and Cicada keeps that
/// small transparent PNG with the look (`design_refs`); here it is tinted to the text colour of either appearance.
/// A look saved without one (before this, or a face that never loaded) sets "Aa" in the family's generic kind — the
/// system's serif, sans or monospace — and says so in words, so a stand-in is never taken for the page's face. The
/// stand-in is data, not interface type (DESIGN_RULES DR-15, dated 2026-10-15). Applies DR-59 (copy), DR-70 (scale).
struct LooksSpecimenList: View {
    let specimens: [DesignSpecimen]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(specimens, id: \.self) { LooksSpecimenRow(specimen: $0) }
        }
    }
}

struct LooksSpecimenRow: View {
    let specimen: DesignSpecimen

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            LooksSpecimenGlyph(specimen: specimen)
                .frame(width: CicadaTheme.scaled(LooksSpecimenGlyph.width),
                       height: CicadaTheme.scaled(LooksSpecimenGlyph.height))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBase))
                .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
                .accessibilityLabel(Copy.Looks.specimenLabel(specimen.family))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(specimen.family).font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary).textSelection(.enabled)
                let uses = Copy.Looks.specimenUses(specimen.roles)
                if !uses.isEmpty {
                    Text(uses).font(CicadaTheme.metaFont).monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if specimen.image == nil {
                    Text(Copy.Looks.specimenGeneric(specimen.generic)).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
    }
}

/// "Aa": the page's own drawing when the look keeps one, else the generic stand-in.
struct LooksSpecimenGlyph: View {
    let specimen: DesignSpecimen
    static let width: CGFloat = 88
    static let height: CGFloat = 52

    @Environment(Store.self) private var store: Store?
    @State private var drawn: NSImage?

    var body: some View {
        ZStack {
            if let drawn {
                Image(nsImage: drawn)
                    .renderingMode(.template)
                    .resizable()
                    .interpolation(.high)
                    .aspectRatio(contentMode: .fit)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .padding(CicadaTheme.scaled(4))
            } else {
                Text("Aa")
                    .font(CicadaTheme.font(size: 30, design: LooksSpecimenFace.design(specimen.generic)))
                    .foregroundStyle(specimen.image == nil ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
            }
        }
        .task(id: "\(store?.bank ?? "")|\(specimen.image?.url ?? "-")") {
            drawn = nil
            guard let url = StoredPreviewPath.url(specimen.image?.url) else { return }
            drawn = await PictureStore.shared.image(url, bank: store?.bank ?? "")
        }
    }
}

/// The generic kind a family falls back to, as a system design — the stand-in when no drawing was kept.
enum LooksSpecimenFace {
    static func design(_ generic: String?) -> Font.Design {
        switch generic?.lowercased() {
        case "serif", "ui-serif": .serif
        case "monospace", "ui-monospace": .monospaced
        case "ui-rounded": .rounded
        default: .default
        }
    }
}
