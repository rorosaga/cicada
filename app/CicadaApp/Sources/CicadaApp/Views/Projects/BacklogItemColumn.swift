import AppKit
import SwiftUI

/// G150 (R-B20, R-B21) — one backlog item as the Projects page's third column: its title as the detail heading
/// (`DetailHeader`, DR-16's H1 role — no new `displayFont` call site, DR-17) with who added it and when; its state,
/// triage and "Paid AI" as `Tag`s (DR-44); the moves it can make and "Edit title" (DR-40; disabled with the reason
/// while Sleep writes, DR-41); the Description and every note as page prose — `MarkdownBody`, because a note is a
/// written document, not words said in a conversation, so not DR-18's quote face; each note signed with its author's
/// real mark and words (DR-52, R-B6); the links; and "Add a note". Esc closes it (DR-28). It draws its own column
/// edge and is never blank (DR-43). The id and the file are in `.help` (R-B24).
struct BacklogItemColumn: View {
    let projectId: String
    let itemId: String
    let onClose: () -> Void
    let onEscape: () -> Void

    @Environment(BacklogCache.self) private var cache
    @Environment(Store.self) private var store
    @State private var note = ""
    @State private var renaming = false
    @State private var newTitle = ""
    @FocusState private var titleFocused: Bool
    /// R-PP5's rule — the viewer's today; midnight re-words the notes' days with no network.
    @State private var today = ISODay.today()

    /// R-PP20 / R-B8 — while Sleep writes, every write control waits, its reason in `.help` (DR-41).
    private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let item = cache.item(projectId, itemId) {
                content(item)
            } else {
                header(title: itemId, blurb: nil, help: itemId)
                switch cache.itemPhase(projectId, itemId) {
                case .gone:
                    Text(Copy.Projects.Backlog.gone)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.Backlog.itemFailedTitle, message: message) {
                        Task { await cache.refreshItem(projectId, itemId) }
                    }
                default:
                    ListSkeleton(message: Copy.Projects.Backlog.readingItem)
                }
                Spacer(minLength: 0)
            }
        }
        .padding(.horizontal, CicadaTheme.scaled(28))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(CicadaTheme.bgBase)
        .columnEdge()
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { if renaming { renaming = false } else { onEscape() } }
        .task(id: BacklogCache.key(projectId, itemId)) { await cache.refreshItem(projectId, itemId) }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    @ViewBuilder
    private func content(_ item: BacklogItem) -> some View {
        let s = item.summary
        header(title: s.title, blurb: BacklogModel.addedLine(s, today: today),
               help: Copy.Projects.Backlog.itemHelp(s.id, path: item.path))
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(22)) {
                tags(s)
                actions(item)
                if renaming { renameRow }
                block(Copy.Projects.Backlog.description) {
                    if item.descriptionText.isEmpty {
                        faint(Copy.Projects.Backlog.noDescription)
                    } else {
                        MarkdownBody(text: item.descriptionText)
                    }
                }
                block(Copy.Projects.Backlog.notesTitle(item.notes.count)) {
                    if item.notes.isEmpty { faint(Copy.Projects.Backlog.noNotes) }
                    ForEach(Array(item.notes.enumerated()), id: \.offset) { _, n in noteRow(n) }
                }
                if !item.links.isEmpty {
                    block(Copy.Projects.Backlog.links) {
                        ForEach(item.links, id: \.self) { link in linkRow(link) }
                    }
                }
                noteField
            }
            .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
            .padding(.bottom, CicadaTheme.scaled(48))
        }
    }

    private func header(title: String, blurb: String?, help: String) -> some View {
        DetailHeader(title: title, blurb: blurb, closeHelp: Copy.Projects.Backlog.closeHelp, onClose: onClose) {
            Image(systemName: "checklist")
                .font(CicadaTheme.icon(.list))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .help(help)
    }

    private func tags(_ s: BacklogItemSummary) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Tag(text: BacklogModel.statusLabel(s.backlogStatus))
            if let triage = BacklogModel.triageLabel(s.triage) { Tag(text: triage) }
            if s.paid { Tag(text: Copy.Projects.Backlog.paid) }
        }
    }

    private func actions(_ item: BacklogItem) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            ForEach(BacklogModel.moves(from: item.summary.backlogStatus), id: \.self) { to in
                NeutralButton(title: BacklogModel.moveLabel(to), size: .compact, isDisabled: blocked,
                              help: BacklogModel.moveHelp(to), disabledHelp: Copy.Projects.sleepRunningHelp) {
                    Task { await write(.update(item: itemId, change: BacklogChange(status: to.rawValue))) }
                }
            }
            TextButton(title: Copy.Projects.Backlog.editTitle, help: Copy.Projects.Backlog.editTitleHelp) {
                newTitle = item.summary.title
                renaming = true
                DispatchQueue.main.async { titleFocused = true }
            }
            .disabled(blocked)
        }
    }

    private var renameRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(Copy.Projects.Backlog.titleLabel, text: $newTitle)
                .textFieldStyle(.roundedBorder)
                .focused($titleFocused)
                .onSubmit { submitTitle() }
                .onExitCommand { renaming = false }
                .accessibilityLabel(Copy.Projects.Backlog.titleLabel)
            TextButton(title: Copy.Projects.cancel) { renaming = false }
            NeutralButton(title: Copy.Projects.Backlog.saveTitle, size: .compact,
                          isDisabled: blocked || newTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                          help: Copy.Projects.Backlog.editTitleHelp,
                          disabledHelp: blocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.Backlog.titleLabel) {
                submitTitle()
            }
        }
    }

    private func block<Body: View>(_ title: String, @ViewBuilder body: () -> Body) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            body()
        }
    }

    private func faint(_ text: String) -> some View {
        Text(text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
    }

    /// R-B6 — the author's real mark (DR-52) and words, the day in `RelativeDay`'s words (DR-58, full date in `.help`),
    /// then the note as page prose.
    private func noteRow(_ n: BacklogNote) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                ContributorAvatar(author: n.by, kind: n.byKind, provider: n.byProvider, size: CicadaTheme.scaled(16))
                Text(BacklogModel.authorLine(n))
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                if let day = ISODay(n.day) {
                    Text(RelativeDay.phrase(day, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .help(RelativeDay.full(day))
                }
            }
            MarkdownBody(text: n.text)
                .padding(.leading, CicadaTheme.scaled(24))
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func linkRow(_ link: BacklogLink) -> some View {
        if link.kind == "url", let url = URL(string: link.ref), url.scheme?.hasPrefix("http") == true {
            InlineLink(title: link.ref, help: link.ref) { NSWorkspace.shared.open(url) }
        } else {
            Text(link.kind == "pr" ? Copy.Projects.Backlog.pullRequest(link.ref) : link.ref)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .textSelection(.enabled)
        }
    }

    private var noteField: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Projects.Backlog.addNote)
            TextField(Copy.Projects.Backlog.notePlaceholder, text: $note, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...8)
                .accessibilityLabel(Copy.Projects.Backlog.addNote)
            HStack {
                Spacer(minLength: 0)
                NeutralButton(title: Copy.Projects.Backlog.saveNote, size: .compact,
                              isDisabled: blocked || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                              help: Copy.Projects.Backlog.saveNoteHelp,
                              disabledHelp: blocked ? Copy.Projects.sleepRunningHelp
                                                    : Copy.Projects.Backlog.notePlaceholder) {
                    let text = note.trimmingCharacters(in: .whitespacesAndNewlines)
                    note = ""
                    Task { await write(.note(item: itemId, text: text, status: nil)) }
                }
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
    }

    private func submitTitle() {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        renaming = false
        guard !title.isEmpty, !blocked, title != cache.item(projectId, itemId)?.summary.title else { return }
        Task { await write(.update(item: itemId, change: BacklogChange(title: title))) }
    }

    /// R-B22 — every write goes through `Store.perform`, then the cache asks again for what the server now holds (a
    /// 304 costs nothing).
    private func write(_ action: BacklogWrite.Action) async {
        _ = await store.perform(BacklogWrite(projectId: projectId, action: action, cache: cache))
        await cache.refreshItem(projectId, itemId)
        await cache.refreshList(projectId)
    }
}
