import AppKit
import SwiftUI

// G230 — a repository page's own card, where a paper's card and a saved link's preview sit (the media page's own
// card, above its article): GitHub's record as the page keeps it, what the person did with it, the projects it belongs
// to (a project may span several repositories — owner 2026-11-03), and its README as words. A project's page lists
// its repositories the same way (`ProjectRepositoriesSection`); linking is the person's act from either page. The README arrives as text only — the backend drops HTML, pictures and badges and keeps a
// link as its words — so the card never loads a picture or a link the README names.
//
// Not a Store domain: `GET /entities/{id}/repository` is read when the card opens and kept in the card's state.
//
// DR-40 (Open on GitHub and the link menu are neutral; a project is a `TextButton` to it), DR-44 (flags and topics are `Tag`s, never a
// filter), DR-47 (the README's label is `SectionLabel`), DR-56 (the README's markdown structure is stripped: a
// heading reads as a heading, a bullet as a bullet, a fence as nothing), DR-58 (dates computed when read),
// DR-71 (only theme tokens, so light and dark both hold), DR-81 (nothing folds; at most five topics, then "+N").

/// Every sentence and decision the card makes, pure — so `RepositoryCardTests` pins them.
enum RepositoryText {
    /// One README line as the card draws it.
    enum Line: Equatable {
        case heading(String, level: Int)
        case text(String)
        case bullet(String)
        case blank
    }

    static let maxTopics = 5

    /// "example-org · Python": who owns it and its language.
    static func byline(_ repo: RepoRow) -> String {
        Eyebrow.text(repo.owner, repo.language ?? "")
    }

    /// The flags worth a `Tag`: private (else public), archived, a fork.
    static func flags(_ repo: RepoRow) -> [String] {
        var out = [repo.isPrivate ? Copy.GitHub.isPrivate : Copy.GitHub.isPublic]
        if repo.archived { out.append(Copy.GitHub.isArchived) }
        if repo.fork { out.append(Copy.GitHub.isFork) }
        return out
    }

    /// At most five topics, then "+N".
    static func topics(_ repo: RepoRow) -> (shown: [String], more: Int) {
        (Array(repo.topics.prefix(maxTopics)), max(0, repo.topics.count - maxTopics))
    }

    /// What the person did with it: "Your repository", "You starred it Sep 12", "No longer starred since Oct 30",
    /// "You added it" (before adds were retired).
    static func relation(_ repo: RepoRow, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        if repo.owned { return Copy.GitHub.yours }
        if repo.starred, let day = ISODay(repo.starredAt) {
            return Copy.GitHub.starredOn(RelativeDay.absolute(day, today: today, locale: locale))
        }
        if !repo.starred, let day = ISODay(repo.unstarredOn) {
            return Copy.GitHub.unstarredOn(RelativeDay.absolute(day, today: today, locale: locale))
        }
        return repo.added ? Copy.GitHub.youAdded : nil
    }

    /// A project in the link menu: the suggestion says why it is first.
    static func candidateLabel(_ project: RepoProject) -> String {
        switch project.how {
        case "name": Copy.GitHub.suggested(project.name)
        case "origin": Copy.GitHub.sameCheckout(project.name)
        default: project.name
        }
    }

    /// How a link was made, when it was not the person: said on hover.
    static func linkHelp(_ how: String, name: String) -> String {
        switch how {
        case "origin": "\(name) · \(Copy.GitHub.byCheckout)"
        case "agent": "\(name) · \(Copy.GitHub.byAgent)"
        default: name
        }
    }

    /// The README's state in words when there is no text to show.
    static func readmeWords(_ readme: RepositoryReadme) -> String? {
        if let text = readme.text, !text.isEmpty { return nil }
        return readme.state == "none" ? Copy.GitHub.readmeNone : Copy.GitHub.readmeMissing
    }

    /// The README as lines: `#` headings, `-`/`*` bullets, fences dropped, runs of blank lines folded to one.
    static func lines(_ text: String) -> [Line] {
        var out: [Line] = []
        for raw in text.replacingOccurrences(of: "\r\n", with: "\n").split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(raw)
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            let isRule = trimmed.count >= 3 && trimmed.allSatisfy { "-=*_".contains($0) }
            if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") || isRule { continue }
            if trimmed.isEmpty {
                if let last = out.last, last != .blank { out.append(.blank) }
                continue
            }
            if trimmed.hasPrefix("#") {
                let level = trimmed.prefix(while: { $0 == "#" }).count
                let words = trimmed.dropFirst(level).trimmingCharacters(in: .whitespaces)
                if level <= 6, !words.isEmpty {
                    out.append(.heading(words, level: level))
                    continue
                }
            }
            if let bullet = ["- ", "* ", "+ "].first(where: { trimmed.hasPrefix($0) }) {
                out.append(.bullet(String(trimmed.dropFirst(bullet.count))))
                continue
            }
            out.append(.text(trimmed.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "`", with: "")))
        }
        while out.first == .blank { out.removeFirst() }
        while out.last == .blank { out.removeLast() }
        return out
    }
}

struct RepositoryCard: View {
    let detail: RepositoryDetail
    /// Open a page (the project this repository is).
    let open: (String) -> Void
    /// After the person made it a project or linked it: the card and the page again.
    let changed: () -> Void

    @State private var busy = false
    @State private var note: String?

    private var repo: RepoRow { detail.repo }
    private var today: ISODay { ISODay.today(now: .now, calendar: .autoupdatingCurrent) }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            header
            if let description = repo.description, !description.isEmpty {
                Text(description)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            tags
            projects
            actions
            if let note {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            readme
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(RepositoryText.byline(repo))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
            if let relation = RepositoryText.relation(repo, today: today) {
                Text(relation)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private var tags: some View {
        let topics = RepositoryText.topics(repo)
        return HStack(spacing: CicadaTheme.spacingXS) {
            ForEach(RepositoryText.flags(repo), id: \.self) { Tag(text: $0) }
            ForEach(topics.shown, id: \.self) { Tag(text: $0) }
            if topics.more > 0 { Tag(text: Copy.GitHub.moreTopics(topics.more)) }
        }
    }

    private var actions: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let url = URL(string: repo.url), url.host?.lowercased() == "github.com" {
                NeutralButton(title: Copy.GitHub.openOnGitHub, systemImage: "arrow.up.right", size: .compact,
                              help: repo.url) { NSWorkspace.shared.open(url) }
            }
            projectAction
        }
    }

    /// The person's link menu: the suggestion first, every other project, then a new project from it.
    private var projectAction: some View {
        RepoLinkMenu(title: Copy.GitHub.linkToProject, help: Copy.GitHub.linkToProjectHelp, busy: busy) {
            ForEach(detail.candidates, id: \.project) { project in
                Button(RepositoryText.candidateLabel(project)) { act(link: project) }
            }
            if !detail.candidates.isEmpty { Divider() }
            Button(Copy.GitHub.newProject) { act(link: nil) }
        }
    }

    /// The projects it belongs to, each a way to its page; Unlink in its menu.
    @ViewBuilder
    private var projects: some View {
        if !repo.projects.isEmpty {
            HStack(spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.GitHub.projectsTitle)
                ForEach(repo.projects, id: \.project) { project in
                    TextButton(title: project.name, help: RepositoryText.linkHelp(project.how, name: project.name),
                               inline: true) { open(project.project) }
                        .contextMenu { Button(Copy.GitHub.unlink) { act(unlink: project) } }
                }
            }
        }
    }

    @ViewBuilder
    private var readme: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .firstTextBaseline) {
                SectionLabel(detail.readme.path ?? Copy.GitHub.readme)
                Spacer(minLength: 0)
                if let day = ISODay(detail.readme.fetchedAt) {
                    Text(Copy.GitHub.readmeAsOf(RelativeDay.phrase(day, today: today)))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .help(day.description)
                }
            }
            if let words = RepositoryText.readmeWords(detail.readme) {
                Text(words).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let text = detail.readme.text {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(Array(RepositoryText.lines(text).enumerated()), id: \.offset) { _, line in
                        lineView(line)
                    }
                }
                .textSelection(.enabled)
                if detail.readme.truncated {
                    Text(Copy.GitHub.readmeCut(text.count)).font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }
        }
    }

    @ViewBuilder
    private func lineView(_ line: RepositoryText.Line) -> some View {
        switch line {
        case .heading(let words, let level):
            Text(words)
                .font(CicadaTheme.font(size: level <= 1 ? 15 : 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
                .padding(.top, CicadaTheme.spacingXS)
                .fixedSize(horizontal: false, vertical: true)
        case .text(let words):
            Text(words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        case .bullet(let words):
            Text("•  " + words).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        case .blank:
            Color.clear.frame(height: CicadaTheme.spacingXS)
        }
    }

    private func act(link project: RepoProject?) {
        run { name in
            let result = try await APIClient.shared.makeRepoProject(fullName: name, project: project?.project)
            return result.created ? Copy.GitHub.started(repo.name) : Copy.GitHub.linked(project?.name ?? repo.name)
        }
    }

    private func act(unlink project: RepoProject) {
        run { name in
            _ = try await APIClient.shared.makeRepoProject(fullName: name, project: project.project, remove: true)
            return Copy.GitHub.unlinked(project.name)
        }
    }

    private func run(_ write: @escaping (String) async throws -> String) {
        busy = true
        let name = repo.fullName
        Task {
            defer { busy = false }
            do {
                note = try await write(name)
                changed()
            } catch {
                note = GitHubReposModel.describe(error)
            }
        }
    }
}

/// The link menus' one look (a compact neutral control that opens a menu, R-HS10's disclosure glyph).
struct RepoLinkMenu<Items: View>: View {
    let title: String
    let help: String
    var busy = false
    @ViewBuilder let items: () -> Items

    var body: some View {
        Menu { items() } label: {
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(title)
                Image(systemName: "chevron.down").font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(CicadaTheme.textPrimary)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .padding(.horizontal, CicadaTheme.scaled(10))
        .frame(height: CicadaTheme.scaled(NeutralButton.Size.compact.height))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgButton))
        .ringed(in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .help(help)
        .disabled(busy)
        .opacity(busy ? NeutralButton.disabledOpacity : 1)
    }
}

/// G230 — a project's repositories, on its page (owner 2026-11-03: "a project might reference several repos"): each
/// one opens its own page (Unlink in its menu), and the person links another from their repository pages. Read when
/// the page opens and after each write; not a Store domain.
struct ProjectRepositoriesSection: View {
    let projectId: String
    let open: (String) -> Void

    @State private var listing: ProjectRepositories?
    @State private var busy = false
    @State private var note: String?

    /// Nothing to show — no repository linked and none to link (GitHub never connected) — draws nothing.
    static func shows(_ listing: ProjectRepositories?) -> Bool {
        guard let listing else { return false }
        return !listing.repos.isEmpty || !listing.candidates.isEmpty
    }

    var body: some View {
        Group {
            if Self.shows(listing), let listing {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(alignment: .firstTextBaseline) {
                        SectionLabel(Copy.GitHub.repositoriesTitle)
                        Spacer(minLength: 0)
                        if !listing.candidates.isEmpty {
                            RepoLinkMenu(title: Copy.GitHub.linkRepository, help: Copy.GitHub.linkRepositoryHelp,
                                         busy: busy) {
                                ForEach(listing.candidates, id: \.url) { repo in
                                    Button(repo.fullName) { write(repo, remove: false) }
                                }
                            }
                        }
                    }
                    if listing.repos.isEmpty {
                        Text(Copy.GitHub.repositoriesEmpty).font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    ForEach(listing.repos, id: \.url) { repo in row(repo) }
                    if let note {
                        Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .task(id: projectId) { await load() }
    }

    private func row(_ repo: RepoRow) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            VStack(alignment: .leading, spacing: 2) {
                Text(repo.fullName).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1).truncationMode(.middle)
                let detail = GitHubReposLogic.detail(repo)
                if !detail.isEmpty {
                    Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let page = repo.entityId {
                NeutralButton(title: Copy.GitHub.open, size: .compact, help: repo.fullName) { open(page) }
            }
        }
        .contentShape(Rectangle())
        .contextMenu { Button(Copy.GitHub.unlink) { write(repo, remove: true) } }
    }

    private func load() async {
        listing = try? await APIClient.shared.fetchProjectRepositories(id: projectId)
    }

    private func write(_ repo: RepoRow, remove: Bool) {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await APIClient.shared.makeRepoProject(fullName: repo.fullName, project: projectId,
                                                              remove: remove)
                note = remove ? Copy.GitHub.unlinked(repo.fullName) : Copy.GitHub.linked(repo.fullName)
                await load()
            } catch {
                note = GitHubReposModel.describe(error)
            }
        }
    }
}
