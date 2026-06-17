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
            Text("Which model — or you — authored each write to memory.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

private struct ContributorRow: View {
    let contributor: Contributor
    let totalCommits: Int

    private var isUser: Bool { contributor.author == "user" }

    private var accent: Color {
        isUser ? Color(hex: 0x3B82F6) : Color(hex: 0x8B5CF6)
    }

    private var share: Double {
        guard totalCommits > 0 else { return 0 }
        return Double(contributor.commitCount) / Double(totalCommits)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack {
                Image(systemName: isUser ? "person.fill" : "cpu")
                    .foregroundStyle(accent)
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
