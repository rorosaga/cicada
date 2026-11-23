import AppKit
import Combine
import SwiftUI

/// G191 v3 — a bookmark's page (the Feed's detail, where the menu bar's history lands): why it was saved, every time
/// it was saved, editable; and Remove (owner 2026-10-15: "where we can modify and edit stuff, or remove the bookmark
/// (which removes it from Chrome too)").
///
/// Each answer is one line of reasons and words with when it was saved and said. Edit opens the same toggles and
/// field the notch panel has (the four reasons, `GET /sources/saved-why/options`; G191 v4: plus whatever the answer
/// already holds that is no longer offered — a retired reason, a project), Save writes
/// `PUT /sources/saved-why` for that answer (or `POST` for a first one) through `Store.perform`. Remove asks first in
/// words, then removes it from Chrome through Apple Events when Chrome holds it (the Automation prompt comes only
/// then), and makes Cicada forget it (`POST /sources/bookmarks/remove`). Safari's bookmarks cannot be changed by
/// another app: the section says so and opens Safari.
///
/// **Nothing written here is lost to Sleep (owner 2026-11-23: "inside the app I tried adding it but it gave me an
/// error because Cicada is currently sleeping … every time I write a reason for saving something, it should save in
/// the app").** A write the backend cannot take yet goes to the notch panel's outbox (`SaveWhyOutbox`) and is sent when
/// Sleep lets go; the list shows every held answer — the panel's too — marked as waiting, so an answer given in the
/// browser while Sleep wrote is visible here at once. An edit shows the words it replaced (`before`).
struct BookmarkReasonsSection: View {
    let item: MediaFeedItem
    var onRemoved: () -> Void = {}

    @Environment(Store.self) private var store
    @Environment(SaveWhyCenter.self) private var saveWhy: SaveWhyCenter?
    @State private var answers: [SavedWhyRecord] = []
    /// Answers about this link the app holds until the backend can take them.
    @State private var held: [SaveWhyOutbox.Entry] = []
    @State private var editing: String?? = nil   // .some(at) edits that answer; .some(nil) adds one
    @State private var reasons: Set<String> = []
    @State private var project: String?
    @State private var words = ""
    @State private var options = BookmarkReasonsSection.cachedOptions
    /// G191 v4 — what the answer being edited holds that is no longer offered (a retired reason, a project): shown as
    /// chips in its editor only, so editing it never drops them unseen and they can be unticked.
    @State private var retired: [SavedWhyOptions.Reason] = []
    @State private var heldProject: String?
    @State private var confirmingRemove = false
    /// What Remove would do in Chrome (nil: Chrome holds no copy), read when the person asks.
    @State private var chromePlan: ChromeRemovalPlan?
    @State private var removing = false

    /// The options, fetched once per launch (the panel's own list).
    @MainActor static var cachedOptions = SavedWhyOptions.basic

    private var fromSafari: Bool { item.origin == "safari-bookmark" }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(Copy.Bookmarks.reasonsLabel)
                .padding(.top, CicadaTheme.scaled(24))
            if let left = Copy.Bookmarks.noLongerIn(item.leftBrowser) {
                // G191 v4: the bookmark left its browser; Cicada kept it — said in words where it shows.
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    Label(left, systemImage: "bookmark.slash")
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text(Copy.Bookmarks.keptNote)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if editing == .some(nil) { editor }
            // 2026-11-23 — how the reason evolved, newest first: one card per answer and per wording it replaced.
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ForEach(Array(timeline.enumerated()), id: \.element.id) { index, entry in
                    if let at = entry.answerAt, editing == .some(at) {
                        editor
                    } else {
                        reasonCard(entry, current: index == 0)
                    }
                }
            }
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
            readHeld()
            editing = nil
            if options == .basic, let fetched = try? await APIClient.shared.savedWhyOptions(), !fetched.reasons.isEmpty {
                Self.cachedOptions = fetched
                options = fetched
            }
        }
        .onChange(of: item.savedWhyAnswers) { _, fresh in if editing == nil { answers = fresh } }
        .onReceive(NotificationCenter.default.publisher(for: SaveWhyOutbox.didChange).receive(on: RunLoop.main)) { _ in
            readHeld()
        }
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

    private func reasonCard(_ entry: ReasonTimeline.Entry, current: Bool) -> some View {
        OriginCard(text: entry.text, origin: entry.origin, date: entry.date,
                   note: entry.held ? Copy.Bookmarks.heldNote : entry.earlier ? Copy.Bookmarks.replacedNote : nil,
                   tone: current ? .current : .past) {
            HStack(alignment: .firstTextBaseline) {
                Text(entry.held ? Copy.Bookmarks.heldLine
                     : entry.record.map { Copy.Bookmarks.answerLine($0, resave: entry.resave) }
                     ?? Copy.Bookmarks.replacedLine(entry.date))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                if editing == nil, let record = entry.record {
                    TextButton(title: Copy.Bookmarks.edit, help: Copy.Bookmarks.edit) { begin(record) }
                }
            }
        }
    }

    /// Every answer and every wording it replaced, newest first.
    private var timeline: [ReasonTimeline.Entry] {
        ReasonTimeline.entries(shown, bookmarkOrigin: item.origin, project: projectName)
    }

    /// The backend's answers with what the app still holds about this link.
    private var shown: [SavedWhyRecord] { SaveWhyOutbox.merge(answers, held: held, labels: labelMap) }

    private var labelMap: [String: String] {
        Dictionary((options.reasons + options.more + retired).map { ($0.key, $0.label) },
                   uniquingKeysWith: { first, _ in first })
    }

    private func readHeld() {
        held = saveWhy?.outbox.held(url: item.url, bank: store.bank) ?? []
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            FlowLayout(spacing: CicadaTheme.scaled(6)) {
                ForEach(offered) { reason in
                    toggle(reason.label, on: reasons.contains(reason.key)) {
                        if reasons.contains(reason.key) { reasons.remove(reason.key) } else { reasons.insert(reason.key) }
                    }
                }
                if let held = heldProject {
                    toggle(projectName(held), on: project == held) { project = project == held ? nil : held }
                }
            }
            TextField("", text: $words)
                .cicadaField(prompt: Copy.Bookmarks.editPrompt, isEmpty: words.isEmpty)
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
                Text(title).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textPrimary)
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
        return SavedWhyAnswer(reasons: offered.map(\.key).filter(reasons.contains), project: project,
                              text: folded.isEmpty ? nil : folded)
    }

    /// The four reasons, then what the edited answer holds that is no longer offered (G191 v4).
    private var offered: [SavedWhyOptions.Reason] { options.reasons + retired }

    private func begin(_ record: SavedWhyRecord?) {
        reasons = Set(record?.reasons ?? [])
        project = record?.project
        heldProject = record?.project
        let keys = Set(options.reasons.map(\.key))
        retired = record.map { r in
            zip(r.reasons, r.labels).filter { !keys.contains($0.0) }.map { SavedWhyOptions.Reason(key: $0.0, label: $0.1) }
        } ?? []
        words = record?.text ?? ""
        editing = .some(record?.at)
    }

    private func save() async {
        guard !answer.isEmpty, let target = editing else { return }
        let labels = Dictionary(offered.map { ($0.key, $0.label) }, uniquingKeysWith: { first, _ in first })
        let url = item.url, bank = store.bank, center = saveWhy
        let answer = answer.given(in: OriginIconography.cicada)
        editing = nil
        // An answer still held is not on the backend yet: the held one changes, and goes when it can.
        if let target, let center, held.contains(where: { $0.editAt == nil && SaveWhyOutbox.stamp($0.at) == target }) {
            center.outbox.holdFromPage(url: url, answer: answer, editAt: target, at: Date(), bank: bank)
            Task { await center.retryHeld() }
            store.flash(Copy.Bookmarks.held)
            return
        }
        let hold: (@MainActor (SavedWhyAnswer, String?) -> Void)? = center.map { center in
            { answer, at in center.outbox.holdFromPage(url: url, answer: answer, editAt: at, at: Date(), bank: bank) }
        }
        let write = SavedWhyWrite(url: url, at: target, answer: answer, answers: $answers, labels: labels, hold: hold)
        if await store.perform(write) { store.flash(write.wasHeld ? Copy.Bookmarks.held : Copy.Bookmarks.saved) }
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

    /// A stored project's name from the graph the Store holds (the panel no longer offers projects, G191 v4).
    private func projectName(_ id: String) -> String {
        let name = store.graph.value?.nodes.first { $0.id == id && $0.type == .project }?.name
        return Copy.SaveWhy.forProject(name ?? id)
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
