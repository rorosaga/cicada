import SwiftUI

// M3 (backlog A2): "which model authored which belief" — repo-wide attribution
// parsed from Cicada-Author commit trailers.
//
// NOT BUILD-VERIFIED — this view was written without an Xcode compile. It mirrors
// the app's existing @Observable + APIClient + CicadaTheme conventions but needs
// Rodrigo to verify it builds and to wire it into the sidebar navigation.
struct ContributorsView: View {
    @State private var viewModel = ContributorsViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            header

            if viewModel.isLoading {
                ProgressView().frame(maxWidth: .infinity, alignment: .center)
            } else if let err = viewModel.errorMessage {
                Text(err)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            } else if viewModel.contributors.isEmpty {
                Text("No attributed commits yet.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(viewModel.contributors) { c in
                            ContributorRow(contributor: c, totalCommits: viewModel.totalCommits)
                        }
                    }
                }
            }

            Spacer()
        }
        .padding(CicadaTheme.spacingLG)
        .task { await viewModel.load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text("Contributors")
                .font(CicadaTheme.titleFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("Which model — or you — authored each belief.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ContributorRow: View {
    let contributor: Contributor
    let totalCommits: Int

    // Prefer the backend-derived `kind`; fall back to the author string so the
    // row still classifies correctly against an older backend (no `kind`).
    private var kind: String {
        if let k = contributor.kind, !k.isEmpty { return k }
        if contributor.author == "user" { return "user" }
        if contributor.author == "unknown" { return "unknown" }
        return "model"
    }

    private var accent: Color {
        switch kind {
        case "user": Color(hex: 0x3B82F6)
        case "unknown": CicadaTheme.textTertiary
        default: ContributorAvatar.providerColor(contributor.provider)
        }
    }

    private var share: Double {
        guard totalCommits > 0 else { return 0 }
        return Double(contributor.commitCount) / Double(totalCommits)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                ContributorAvatar(contributor: contributor, kind: kind)
                Text(contributor.author)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Spacer()
                Text("\(contributor.commitCount) commits")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }

            HStack(spacing: CicadaTheme.spacingMD) {
                Text("\(contributor.entityCount) entities")
                Text("\(contributor.fileCount) files")
                if !contributor.lastActive.isEmpty {
                    Text("last \(contributor.lastActive)")
                }
            }
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(CicadaTheme.border)
                        .frame(height: 4)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(accent)
                        .frame(width: geo.size.width * share, height: 4)
                }
            }
            .frame(height: 4)
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.surfaceHover.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
    }
}

// G15 — a per-contributor avatar (GitHub-repo-contributors style).
//   user    -> the user's GitHub profile picture (rounded), falling back to a
//              person glyph if there's no URL or the image fails to load.
//   model   -> a provider badge: a colored circle with a 1-letter monogram
//              (provider brand-ish colors; "other" neutral). Real logo assets
//              are a follow-up; the monogram badge is the v1.
//   unknown -> a muted question-mark glyph.
private struct ContributorAvatar: View {
    let contributor: Contributor
    let kind: String

    private static let size: CGFloat = 22

    var body: some View {
        switch kind {
        case "user":
            userAvatar
        case "unknown":
            Image(systemName: "questionmark.circle.fill")
                .font(.system(size: Self.size))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: Self.size, height: Self.size)
        default:
            providerBadge
        }
    }

    @ViewBuilder
    private var userAvatar: some View {
        if let urlStr = contributor.avatarUrl, let url = URL(string: urlStr) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                case .empty:
                    ProgressView().scaleEffect(0.5)
                default:
                    userFallback
                }
            }
            .frame(width: Self.size, height: Self.size)
            .clipShape(Circle())
        } else {
            userFallback
        }
    }

    private var userFallback: some View {
        Image(systemName: "person.crop.circle.fill")
            .font(.system(size: Self.size))
            .foregroundStyle(Color(hex: 0x3B82F6))
            .frame(width: Self.size, height: Self.size)
    }

    private var providerBadge: some View {
        Circle()
            .fill(Self.providerColor(contributor.provider))
            .frame(width: Self.size, height: Self.size)
            .overlay(
                Text(Self.monogram(contributor.provider))
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(.white)
            )
    }

    /// Brand-ish color per provider; "other"/unknown -> a neutral tone.
    static func providerColor(_ provider: String?) -> Color {
        switch provider {
        case "anthropic": Color(hex: 0xD97757)  // Anthropic clay/terracotta
        case "openai": Color(hex: 0x10A37F)      // OpenAI teal-green
        case "google": Color(hex: 0x4285F4)      // Google blue
        default: CicadaTheme.textTertiary        // "other" / unknown — neutral
        }
    }

    /// 1-letter monogram per provider.
    static func monogram(_ provider: String?) -> String {
        switch provider {
        case "anthropic": "A"
        case "openai": "O"
        case "google": "G"
        default: "?"
        }
    }
}
