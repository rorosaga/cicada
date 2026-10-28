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

/// G61 — how a link reads in a chip or a review row: the server's label and link kind, except an X profile, which
/// reads "@handle" with the X glyph whatever the server sent (review of #428; #422 fixes the server side too). One
/// helper for the Inbox's review rows and the entity card's chips.
enum LinkWords {
    struct Words: Equatable {
        let label: String
        let kind: String
    }

    static let xHosts: Set<String> = ["x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"]

    static func of(ref: String, label: String?, linkKind: String?) -> Words {
        if let handle = xHandle(ref) { return Words(label: "@" + handle, kind: "x") }
        let words = (label ?? "").trimmingCharacters(in: .whitespaces)
        return Words(label: words.isEmpty ? ref : words, kind: linkKind ?? "website")
    }

    /// The first path segment of an x.com / twitter.com link, when there is one.
    static func xHandle(_ ref: String) -> String? {
        guard let url = URL(string: ref), let raw = url.host?.lowercased() else { return nil }
        let host = raw.hasPrefix("www.") ? String(raw.dropFirst(4)) : raw
        guard xHosts.contains(host) else { return nil }
        let first = url.path.split(separator: "/").first.map(String.init) ?? ""
        let handle = first.hasPrefix("@") ? String(first.dropFirst()) : first
        return handle.isEmpty ? nil : handle
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

/// G61 — "Confirm N links". Inbox v2 (owner 2026-10-26: "I don't really get the confirmation of links"): the card says
/// what it is in one sentence, then each page once — its picture and name (a click opens it) — and under it each
/// waiting link: what it is ("bob-example · GitHub profile"), why Cicada proposed it, and what confirming changes
/// ("their picture and updates can come from here"). One quiet primary per link (Confirm, a neutral button, DR-40) and
/// a quieter decline (a text button). Past three pages, "All N pages" opens every page in a sheet (ruling 48 (17): no fold). Each link
/// is still answered alone; there is no answer-all, and the card leaves when the last is answered.
struct WhereToCheckReviewCard: View {
    let item: InboxItem
    var openPage: (String) -> Void = { _ in }

    @Environment(Store.self) private var store
    @State private var answered: Set<String> = []
    @State private var showAll = false

    private var rows: [WhereToCheckRow] { (item.rows ?? []).filter { !answered.contains($0.id) } }

    var body: some View {
        let pages = WhereToCheckWords.byPage(rows)
        if !pages.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                Text(item.questionText)
                    .font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
                Text(Copy.WhereToCheck.explainer)
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
                    .padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    ForEach(pages.prefix(WhereToCheckWords.firstPages)) { page in pageView(page) }
                }
                .padding(.top, CicadaTheme.spacingMD)
                // Ruling 48 (17), DR-81 — no fold: the first pages open, "All N pages" opens every page in a sheet.
                if pages.count > WhereToCheckWords.firstPages {
                    InlineLink(title: Copy.WhereToCheck.allPages(pages.count), help: Copy.WhereToCheck.showMoreHelp) {
                        showAll = true
                    }
                    .padding(.top, CicadaTheme.spacingSM)
                }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.bgFocus, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
            .sheet(isPresented: $showAll) {
                FullListSheet(title: item.questionText) {
                    ForEach(WhereToCheckWords.byPage(rows)) { page in pageView(page) }
                }
                .environment(store)
            }
        }
    }

    /// One page: its picture and name once, then its waiting links.
    private func pageView(_ page: WhereToCheckWords.PageRows) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.scaled(12)) {
            EntityPicture(id: page.page, name: page.pageName, type: EntityType(rawValue: page.pageType) ?? .unknown,
                          size: 28)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Button { openPage(page.page) } label: {
                    Text(page.pageName)
                        .font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Inbox.openPageHelp(page.pageName))
                ForEach(page.rows) { row in rowView(row) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .contain)
    }

    private func rowView(_ row: WhereToCheckRow) -> some View {
        let words = LinkWords.of(ref: row.ref, label: row.label, linkKind: row.linkKind)
        let short = WhereToCheckWords.shortRef(row.ref)
        return HStack(alignment: .top, spacing: CicadaTheme.spacingSM) {
            Image(systemName: LinkKindGlyph.symbol(words.kind))
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(16))
                .padding(.top, CicadaTheme.scaled(2))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                HStack(spacing: CicadaTheme.scaled(6)) {
                    Text(words.label)
                        .font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    Text(Eyebrow.text(WhereToCheckWords.kindName(words.kind, pageType: row.pageType),
                                      short == words.label ? "" : short))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1).truncationMode(.middle)
                }
                Text(WhereToCheckWords.why(row) + " " + WhereToCheckWords.effect(row, kind: words.kind))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.textMaxWidth), alignment: .leading)
            }
            .help(Self.evidenceWords(row))
            Spacer(minLength: CicadaTheme.spacingSM)
            NeutralButton(title: Copy.WhereToCheck.confirm, size: .compact,
                          help: Copy.WhereToCheck.rowHelp(yes: true, label: words.label)) { answer(row, take: true) }
            // One column for the answers, whatever the decline says, so every Confirm lines up.
            TextButton(title: WhereToCheckWords.declineLabel(row),
                       help: Copy.WhereToCheck.rowHelp(yes: false, label: words.label)) { answer(row, take: false) }
                .frame(minWidth: CicadaTheme.scaled(104), alignment: .leading)
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
