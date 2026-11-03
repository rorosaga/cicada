import AppKit
import SwiftUI

// G230 — a repository page's own card, where a paper's card and a saved link's preview sit (the media page's own
// card, above its article): GitHub's record as the page keeps it, what the person did with it, the project it is,
// and its README as words. The README arrives as text only — the backend drops HTML, pictures and badges and keeps a
// link as its words — so the card never loads a picture or a link the README names.
//
// Not a Store domain: `GET /entities/{id}/repository` is read when the card opens and kept in the card's state.
//
// DR-40 (Open on GitHub and the project action are `NeutralButton`s), DR-44 (flags and topics are `Tag`s, never a
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

    /// What the person did with it: "You starred it Sep 12", "No longer starred since Oct 30", "You added it".
    static func relation(_ repo: RepoRow, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String? {
        if repo.starred, let day = ISODay(repo.starredAt) {
            return Copy.GitHub.starredOn(RelativeDay.absolute(day, today: today, locale: locale))
        }
        if !repo.starred, let day = ISODay(repo.unstarredOn) {
            return Copy.GitHub.unstarredOn(RelativeDay.absolute(day, today: today, locale: locale))
        }
        return repo.added ? Copy.GitHub.youAdded : nil
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

    @ViewBuilder
    private var projectAction: some View {
        if let project = repo.project, project.isSettled {
            TextButton(title: Copy.GitHub.yourProject(project.name), help: project.name) { open(project.project) }
        } else if repo.owned {
            if let project = repo.project {
                NeutralButton(title: Copy.GitHub.linkTo(project.name), size: .compact, isDisabled: busy,
                              help: Copy.GitHub.linkToHelp(project.name)) { act(link: project) }
            }
            NeutralButton(title: Copy.GitHub.makeProject, size: .compact, isDisabled: busy,
                          help: Copy.GitHub.makeProjectHelp) { act(link: nil) }
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
        busy = true
        let name = repo.fullName
        Task {
            defer { busy = false }
            do {
                let result = try await APIClient.shared.makeRepoProject(fullName: name, project: project?.project)
                note = result.created ? Copy.GitHub.started(repo.name) : Copy.GitHub.linked(project?.name ?? repo.name)
                changed()
            } catch {
                note = GitHubReposModel.describe(error)
            }
        }
    }
}
