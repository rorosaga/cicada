import SwiftUI

/// What a link is, as one glyph (G61 `linkKind`): a person's page never shows a third-party logo (G159), so every
/// chip and review row wears this instead, and only a trusted site on a non-person page its own icon.
enum LinkKindGlyph {
    static func symbol(_ kind: String) -> String {
        switch kind {
        case "github", "repo": "chevron.left.forwardslash.chevron.right"
        case "x": "at"
        case "instagram": "camera"
        case "linkedin": "briefcase"
        case "scholar": "graduationcap"
        case "orcid": "person.text.rectangle"
        case "contacts": "person.crop.circle"
        case "app": "app"
        case "path": "folder"
        case "note": "text.quote"
        default: "globe"
        }
    }
}

/// G205 / G61 — the cards above the questions: agents asking, the in-words notification ask, and the grouped
/// Where-to-check review. Small, one group each (DR-37), ringed not shadowed (DR-9), no primary button (DR-40: the
/// Inbox has none).
struct InboxTopCards: View {
    let requests: [InboxItem]
    let reviews: [InboxItem]
    let answer: (InboxItem, QuestionResolution) -> Void
    var openPage: (String) -> Void = { _ in }

    @State private var notifier = AgentRequestNotifier.shared

    var body: some View {
        if !requests.isEmpty || !reviews.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(requests) { item in
                    AgentRequestCard(item: item, answer: answer)
                }
                if !requests.isEmpty, notifier.asksInWords {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.AgentRequests.askLine)
                            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        TextButton(title: Copy.AgentRequests.notifyMe, inline: true) {
                            Task { await notifier.requestPermission() }
                        }
                    }
                    .padding(.horizontal, CicadaTheme.scaled(10))
                }
                ForEach(reviews) { item in
                    WhereToCheckReviewCard(item: item, openPage: openPage)
                }
            }
            .padding(.bottom, CicadaTheme.spacingMD)
        }
    }
}

/// One agent's request: its mark, "Sign in to example.com", whose and why, then "I signed in" and "Not now".
struct AgentRequestCard: View {
    let item: InboxItem
    let answer: (InboxItem, QuestionResolution) -> Void

    private var request: AgentRequestInfo? { item.request }

    var body: some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(12)) {
            SourceLogoTile(origin: request?.agent ?? "other", logo: request?.logo)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                Text(Copy.AgentRequests.title(site: request?.site))
                    .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(Eyebrow.text(request?.agentName ?? item.displayName, request?.reason ?? ""))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
                HStack(spacing: CicadaTheme.spacingSM) {
                    NeutralButton(title: Copy.AgentRequests.signedIn, size: .compact) {
                        answer(item, QuestionResolution(action: "resolve", optionKey: "done"))
                    }
                    TextButton(title: Copy.AgentRequests.notNow) {
                        answer(item, QuestionResolution(action: "resolve", optionKey: "dismiss"))
                    }
                }
                .padding(.top, CicadaTheme.spacingXS)
            }
            Spacer(minLength: 0)
            if let url = openURL, let site = request?.site {
                IconButton(systemName: "arrow.up.forward.square", help: Copy.AgentRequests.open(site)) {
                    NSWorkspace.shared.open(url)
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
        .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityElement(children: .contain)
    }

    private var openURL: URL? {
        guard let raw = request?.notification?.openUrl, let url = URL(string: raw),
              ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return nil }
        return url
    }
}

/// G61 — "Confirm N links": one row per waiting link (its kind's glyph, the link, the page it is for, where it was
/// found on hover), each answered alone with Yes / No; the card leaves when the last row is answered.
struct WhereToCheckReviewCard: View {
    let item: InboxItem
    var openPage: (String) -> Void = { _ in }

    @Environment(Store.self) private var store
    @State private var answered: Set<String> = []

    private var rows: [WhereToCheckRow] { (item.rows ?? []).filter { !answered.contains($0.id) } }

    var body: some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(item.questionText)
                    .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                    ForEach(rows) { row in rowView(row) }
                }
            }
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        }
    }

    private func rowView(_ row: WhereToCheckRow) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: LinkKindGlyph.symbol(row.linkKind))
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(18))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(1)) {
                Text(row.label.isEmpty ? row.ref : row.label)
                    .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                Button { openPage(row.page) } label: {
                    Text(row.pageName.isEmpty ? row.page : row.pageName)
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
                .buttonStyle(.cicadaPlain)
            }
            .help(Self.evidenceWords(row))
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.WhereToCheck.yes, size: .compact,
                          help: Copy.WhereToCheck.rowHelp(yes: true, label: row.label)) { answer(row, take: true) }
            TextButton(title: Copy.WhereToCheck.no,
                       help: Copy.WhereToCheck.rowHelp(yes: false, label: row.label)) { answer(row, take: false) }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
    }

    /// Where the link was found, in words (DR-54: never an episode id).
    static func evidenceWords(_ row: WhereToCheckRow) -> String {
        guard let evidence = row.evidence else { return row.ref }
        if evidence.page == true { return "\(row.ref)\n\(Copy.WhereToCheck.fromPage)" }
        let who = (evidence.kind ?? "user") == "user" ? Copy.WhereToCheck.fromYou : Copy.WhereToCheck.fromAgent
        return "\(row.ref)\n\(who)"
    }

    /// Optimistic: the row leaves at the tap and comes back with a toast if the answer never landed.
    private func answer(_ row: WhereToCheckRow, take: Bool) {
        answered.insert(row.id)
        Task {
            do {
                try await APIClient.shared.resolveWhereToCheckRow(id: item.id, row: row.id, take: take)
                await store.refresh([.inbox])
            } catch {
                answered.remove(row.id)
                store.toast = Copy.WhereToCheck.failed
            }
        }
    }
}
