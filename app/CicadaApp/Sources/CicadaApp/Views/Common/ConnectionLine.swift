import SwiftUI

/// One connection, one line (G217): `LogoTile` · name (and one quiet detail line) · a dot and one word · its actions.
/// Every list of things that connect to Cicada draws this — Intelligence, Devices, You's profiles, the Agents page — so
/// the marks, the status and the spacing read the same everywhere (DR-34: one height per row role).
struct ConnectionLine<Trailing: View, Below: View>: View {
    var logo: String?
    var name: String
    var bundleId: String? = nil
    var systemFallback: String = LogoTile.monogramFallback
    var detail: String? = nil
    var status: (word: String, on: Bool)? = nil
    var quiet = false
    var detailLines = 3
    /// Looks pass (2026-10-23): in a narrow column (a list beside its detail) the dot and word go under the name, so
    /// the name keeps the row's width — trailing, "Not set up" cut every name to "O…" at 280 pt.
    var statusBelowName = false
    @ViewBuilder var trailing: () -> Trailing
    @ViewBuilder var below: () -> Below

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoTile(logo: logo, name: name, bundleId: bundleId, systemFallback: systemFallback)
                    .opacity(quiet ? 0.6 : 1)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Text(name)
                        .font(CicadaTheme.rowFont)
                        .foregroundStyle(quiet ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    if statusBelowName, let status {
                        StatusDot(word: status.word, on: status.on)
                    } else if let detail, !detail.isEmpty {
                        Text(detail)
                            .font(CicadaTheme.captionFont.monospacedDigit())
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .lineLimit(detailLines)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let status, !statusBelowName { StatusDot(word: status.word, on: status.on) }
                trailing()
            }
            below()
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension ConnectionLine where Below == EmptyView {
    init(logo: String?, name: String, bundleId: String? = nil, systemFallback: String = LogoTile.monogramFallback, detail: String? = nil,
         status: (word: String, on: Bool)? = nil, quiet: Bool = false, detailLines: Int = 3,
         statusBelowName: Bool = false, @ViewBuilder trailing: @escaping () -> Trailing) {
        self.init(logo: logo, name: name, bundleId: bundleId, systemFallback: systemFallback, detail: detail,
                  status: status, quiet: quiet, detailLines: detailLines, statusBelowName: statusBelowName,
                  trailing: trailing, below: { EmptyView() })
    }
}

/// `GET /providers`, once per launch, kept in memory (static per release — no Store domain, no ETag; the route says so).
@MainActor @Observable
final class ProviderDirectory {
    static let shared = ProviderDirectory()
    private(set) var providers: [ProviderUmbrella] = []
    private var loaded = false

    func load() async {
        guard !loaded else { return }
        if let answer = try? await APIClient.shared.fetchProviders(), !answer.providers.isEmpty {
            providers = answer.providers
            loaded = true
        }
    }

    /// The umbrellas that run Sleep, split as Intelligence draws them.
    var intelligence: [(umbrella: ProviderUmbrella, item: ProviderIntelligence)] {
        providers.flatMap { u in u.intelligence.map { (u, $0) } }
    }

    /// The umbrellas agents connect through — every one with a way in.
    var agents: [ProviderUmbrella] { providers.filter { !$0.ways.isEmpty } }

    /// `/providers` names the local engine `ollama`; `/connections` calls it `ollama-local`.
    nonisolated static func connectionId(_ id: String) -> String { id == "ollama" ? "ollama-local" : id }
}
