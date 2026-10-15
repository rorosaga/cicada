import AppKit
import SwiftUI

/// G191 v3 — a bookmark's page (the Feed's detail, where the menu bar's history lands): why it was saved, every time
/// it was saved, editable; and Remove (owner 2026-10-15: "where we can modify and edit stuff, or remove the bookmark
/// (which removes it from Chrome too)").
///
/// Each answer is one line of reasons and words with when it was saved and said. Edit opens the same toggles and
/// field the notch panel has (the backend's reasons and live projects, `GET /sources/saved-why/options`), Save writes
/// `PUT /sources/saved-why` for that answer (or `POST` for a first one) through `Store.perform`. Remove asks first in
/// words, then removes it from Chrome through Apple Events when Chrome holds it (the Automation prompt comes only
/// then), and makes Cicada forget it (`POST /sources/bookmarks/remove`). Safari's bookmarks cannot be changed by
/// another app: the section says so and opens Safari.
struct BookmarkReasonsSection: View {
    let item: MediaFeedItem
    var onRemoved: () -> Void = {}

    @Environment(Store.self) private var store
    @State private var answers: [SavedWhyRecord] = []
    @State private var editing: String?? = nil   // .some(at) edits that answer; .some(nil) adds one
    @State private var reasons: Set<String> = []
    @State private var project: String?
    @State private var words = ""
    @State private var options = BookmarkReasonsSection.cachedOptions
    @State private var confirmingRemove = false
    /// What Remove would do in Chrome (nil: Chrome holds no copy), read when the person asks.
    @State private var chromePlan: ChromeRemovalPlan?
    @State private var removing = false

    /// The options, fetched once per launch (the panel's own list).
    @MainActor static var cachedOptions = SavedWhyOptions()

    private var fromSafari: Bool { item.origin == "safari-bookmark" }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Bookmarks.reasonsLabel)
                .padding(.top, CicadaTheme.scaled(24))
            ForEach(Array(answers.enumerated().reversed()), id: \.offset) { index, record in
                if editing == .some(record.at) {
                    editor
                } else {
                    answerRow(record, resave: index > 0)
                }
            }
            if editing == .some(nil) { editor }
            HStack(spacing: CicadaTheme.spacingMD) {
                if editing == nil {
                    TextButton(title: Copy.Bookmarks.addReason, help: Copy.Bookmarks.addReason) { begin(nil) }
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                Spacer()
                TextButton(title: Copy.Bookmarks.remove, help: Copy.Bookmarks.removeTitle) {
                    Task {
                        chromePlan = await ChromeBookmarkRemoval.plan(url: item.url, lastSavedAt: item.lastSavedAt)
                        confirmingRemove = true
                    }
                }
                .disabled(removing)
            }
            if fromSafari {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Bookmarks.safariNote)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                    TextButton(title: Copy.Bookmarks.openSafari, help: Copy.Bookmarks.openSafari) { openSafari() }
                }
            }
        }
        .task(id: item.id) {
            answers = item.savedWhyAnswers
            editing = nil
            if options.reasons.isEmpty, let fetched = try? await APIClient.shared.savedWhyOptions() {
                Self.cachedOptions = fetched
                options = fetched
            }
        }
        .onChange(of: item.savedWhyAnswers) { _, fresh in if editing == nil { answers = fresh } }
        .confirmationDialog(Copy.Bookmarks.removeTitle, isPresented: $confirmingRemove) {
            if let plan = chromePlan, plan.hasSeveral {
                // Several copies of the link in Chrome: only this save's copy unless the person asks for all.
                Button(Copy.Bookmarks.removeOneCopy(plan.target?.addedAt.flatMap(Copy.Bookmarks.day)),
                       role: .destructive) { Task { await remove(chrome: plan.target.map { [$0] } ?? []) } }
                Button(Copy.Bookmarks.removeAllCopies(plan.copies.count), role: .destructive) {
                    Task { await remove(chrome: plan.copies) }
                }
            } else {
                Button(Copy.Bookmarks.removeConfirm, role: .destructive) {
                    Task { await remove(chrome: chromePlan?.target.map { [$0] } ?? []) }
                }
            }
            Button(Copy.Bookmarks.cancel, role: .cancel) {}
        } message: {
            Text(BookmarkRemoveFlow.confirmation(plan: chromePlan, fromSafari: fromSafari))
        }
    }

    private func answerRow(_ record: SavedWhyRecord, resave: Bool) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
            HStack(alignment: .firstTextBaseline) {
                Text(Copy.Bookmarks.answerLine(record, resave: resave))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                Spacer()
                if editing == nil {
                    TextButton(title: Copy.Bookmarks.edit, help: Copy.Bookmarks.edit) { begin(record) }
                }
            }
            let names = record.labels + (record.project.map { [projectName($0)] } ?? [])
            if !names.isEmpty {
                Text(names.joined(separator: " · "))
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if let text = record.text, !text.isEmpty {
                Text("“\(text)”") // count-lint:ok — the person's quoted words, no number
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            FlowLayout(spacing: CicadaTheme.scaled(6)) {
                ForEach(options.reasons) { reason in
                    toggle(reason.label, on: reasons.contains(reason.key)) {
                        if reasons.contains(reason.key) { reasons.remove(reason.key) } else { reasons.insert(reason.key) }
                    }
                }
                ForEach(options.projects) { p in
                    toggle(Copy.SaveWhy.forProject(p.name), on: project == p.id) {
                        project = project == p.id ? nil : p.id
                    }
                }
            }
            TextField(Copy.Bookmarks.editPrompt, text: $words)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await save() } }
            HStack(spacing: CicadaTheme.spacingSM) {
                NeutralButton(title: Copy.Bookmarks.save, size: .compact) { Task { await save() } }
                    .disabled(answer.isEmpty)
                TextButton(title: Copy.Bookmarks.cancel, help: Copy.Bookmarks.cancel) { editing = nil }
            }
        }
        .padding(.vertical, CicadaTheme.spacingXS)
    }

    private func toggle(_ title: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.scaled(5)) {
                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                    .font(CicadaTheme.font(size: 11))
                    .foregroundStyle(on ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                Text(title).font(CicadaTheme.font(size: 12)).foregroundStyle(CicadaTheme.textPrimary)
            }
            .padding(.leading, CicadaTheme.scaled(8))
            .padding(.trailing, CicadaTheme.scaled(10))
            .padding(.vertical, CicadaTheme.scaled(5))
            .background(Capsule().fill(on ? CicadaTheme.bgSelected : Color.clear))
            .overlay(Capsule().strokeBorder(CicadaTheme.borderLight, lineWidth: 1))
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityAddTraits(on ? [.isSelected, .isToggle] : [.isToggle])
    }

    private var answer: SavedWhyAnswer {
        let folded = words.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return SavedWhyAnswer(reasons: options.reasons.map(\.key).filter(reasons.contains), project: project,
                              text: folded.isEmpty ? nil : folded)
    }

    private func begin(_ record: SavedWhyRecord?) {
        reasons = Set(record?.reasons ?? [])
        project = record?.project
        words = record?.text ?? ""
        editing = .some(record?.at)
    }

    private func save() async {
        guard !answer.isEmpty, let target = editing else { return }
        let labels = Dictionary(uniqueKeysWithValues: options.reasons.map { ($0.key, $0.label) })
        let write = SavedWhyWrite(url: item.url, at: target, answer: answer, answers: $answers, labels: labels)
        editing = nil
        if await store.perform(write) { store.flash(Copy.Bookmarks.saved) }
    }

    private func remove(chrome nodes: [BookmarkEntry]) async {
        removing = true
        defer { removing = false }
        let url = item.url
        let unreachable = chromePlan?.unreachable ?? 0
        let message = await BookmarkRemoveFlow.run(
            forget: { await store.perform(BookmarkRemove(url: url)) },
            chrome: chromePlan == nil ? nil : {
                await ChromeBookmarkRemoval.remove(url, nodes: nodes, unreachable: unreachable)
            })
        guard let message else { return }   // the backend refused: Chrome untouched, the store toasted why
        store.toast = message
        onRemoved()
    }

    private func projectName(_ id: String) -> String {
        options.projects.first { $0.id == id }.map { Copy.SaveWhy.forProject($0.name) } ?? Copy.SaveWhy.forProject(id)
    }

    private func openSafari() {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Safari") else { return }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
    }
}

/// Review 2026-10-15 — the order of Remove: Cicada forgets the bookmark first (the backend may refuse, e.g. 409 while
/// Sleep writes), and Chrome is touched only once that succeeded. Returns the line to show, or nil when the backend
/// refused (and Chrome was never asked).
enum BookmarkRemoveFlow {
    @MainActor
    static func run(forget: () async -> Bool,
                    chrome: (() async -> ChromeBookmarkRemoval.Outcome)?) async -> String? {
        guard await forget() else { return nil }
        guard let chrome else { return Copy.Bookmarks.removed }
        return ChromeBookmarkRemoval.message(await chrome())
    }

    static func confirmation(plan: ChromeRemovalPlan?, fromSafari: Bool) -> String {
        if let plan, plan.hasSeveral { return Copy.Bookmarks.chromeCopies(plan.copies.count) }
        if let plan, !plan.copies.isEmpty || plan.unreachable > 0 { return Copy.Bookmarks.removeFromChrome }
        return fromSafari ? Copy.Bookmarks.removeCicadaOnly + " " + Copy.Bookmarks.safariNote
                          : Copy.Bookmarks.removeCicadaOnly
    }
}
