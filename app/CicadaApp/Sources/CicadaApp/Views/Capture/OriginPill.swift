import SwiftUI

// MARK: - Origin pill

/// One capture-origin readout in the Capture page's "where your memory comes
/// from" strip. Pill/capsule styling mirrors `ContributorAvatar`/`ClaimChip`'s
/// provenance pills so provenance reads consistently across the app; icon and
/// brand color mirror `CaptureSourceCatalog` where the origin has a known source.
struct OriginPill: View {
    let origin: OriginStat

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: symbol)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(color)
            Text(label)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("\(origin.episodeCount) ep · \(origin.entityCount) ent")
                .font(.system(size: 10, weight: .regular))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(color.opacity(0.3), lineWidth: 1))
        .help(origin.lastSeen.isEmpty ? label : "\(label) · last seen \(origin.lastSeen)")
    }

    // Delegates to `OriginIconography` (G106 amendment extracted it out so
    // the Sleep debt breakdown's per-source grouping can share the exact
    // same label/symbol/color mapping instead of re-declaring it).
    private var label: String { OriginIconography.label(for: origin.origin) }
    private var symbol: String { OriginIconography.symbol(for: origin.origin) }
    private var color: Color { OriginIconography.color(for: origin.origin) }
}
