import SwiftUI

/// In motion (§6.3; Projects v3, decision 9): the ongoing threads — heard-from first, then quiet — each with its line
/// of days; a quiet one whose follow-up waits in the Inbox links to that card (R-PP18). At most `limit` rows (the rest
/// behind the section's "All N"); under them, the Sleep queue's honest line (§6.1 layer 7). An empty section is never
/// drawn, so there is no "nothing in motion" line here. Task 5 passes `settle`, which draws Done · Still going · Stopped.
struct ProjectNowSection: View {
    let timeline: ProjectTimeline
    let state: ProjectState.Output
    let today: ISODay
    let selection: ProjectKey?
    let followups: [String: InboxItem]
    let pick: (ProjectKey) -> Void
    let openEntity: (String) -> Void
    let showSource: (ProjectKey) -> Void
    let openInbox: (String) -> Void
    var settle: ((String, String) -> Void)? = nil
    var writesBlocked = false
    var limit: Int? = nil

    var body: some View {
        let threads = ProjectStory.nowThreads(timeline, state: state)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(limit.map { Array(threads.prefix($0)) } ?? threads) { thread in
                row(thread).id(ProjectKey.thread(thread.claimId).id)
            }
            if let pending = ProjectStory.pendingLine(timeline.pending, today: today) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "hourglass").font(CicadaTheme.icon(.inline)).accessibilityHidden(true)
                    Text(pending)
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .help(Copy.Projects.waitingHelp)
            }
        }
    }

    private func row(_ thread: ProjectOpenThread) -> some View {
        let key = ProjectKey.thread(thread.claimId)
        let selected = selection == key
        let item = timeline.items.first { $0.id == thread.claimId }
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                StoryGlyph(glyph: .ongoing).padding(.top, CicadaTheme.scaled(6))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    StorySentence(text: thread.text, participants: item?.participants ?? [], total: item?.participantsTotal,
                                  openEntity: openEntity)
                    Text(ProjectStory.threadMeta(thread, state: state, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                if let followup = followups[thread.claimId] {
                    InlineLink(title: Copy.Projects.howDidItGo, help: Copy.Projects.howDidItGoHelp) { openInbox(followup.id) }
                } else if let settle, timeline.holds(thread.on) {
                    HStack(spacing: CicadaTheme.spacingXS) {
                        NeutralButton(title: Copy.Projects.done, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.doneHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "done")
                        }
                        NeutralButton(title: Copy.Projects.stillGoing, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.stillGoingHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "ongoing")
                        }
                        NeutralButton(title: Copy.Projects.stopped, size: .compact, isDisabled: writesBlocked,
                                      help: Copy.Projects.stoppedHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                            settle(thread.claimId, "dropped")
                        }
                    }
                }
            }
            if selected, let item {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    if let ev = ProjectSource.evidence(item) { ProjectQuoteBlock(evidence: ev) }
                    ProjectSourceLineView(line: ProjectSource.line(item), evidence: ProjectSource.evidence(item),
                                          subjectId: item.claim?.subject ?? timeline.project.id, showing: false,
                                          show: ProjectSource.target(item, projectId: timeline.project.id) == nil
                                              ? nil : { showSource(key) })
                }
                .padding(.leading, CicadaTheme.scaled(22))
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

extension ProjectStory.LatelyEntry {
    /// R-FA3 — the gaps the nested stacks used to give: header → first label `spacingSM`, between groups
    /// `spacingMD`, between rows `spacingXS`.
    var topPadding: CGFloat {
        switch self {
        case .label(_, let first): first ? CicadaTheme.spacingSM : CicadaTheme.spacingMD
        case .item: CicadaTheme.spacingXS
        }
    }
}

/// Lately's day label (Today · Yesterday · This week · Earlier) — a direct child of the column's lazy stack (R-FA3).
struct ProjectLatelyLabel: View {
    let group: RelativeDay.Group

    var body: some View {
        SectionLabel(RelativeDay.title(group)).padding(.horizontal, CicadaTheme.spacingMD)
    }
}

/// Lately (the brief): Today · Yesterday · This week · Earlier — each happening ONE sentence with its participants as
/// chips, a status word and its date, and its source line; selected, its words, how it was dated, Resume where
/// resumable (R-PP26) and — Task 5 — "Not right". One row, a direct child of the column's lazy stack (R-FA3), so a
/// long story builds only the rows on screen; `created` is `ProjectLatelyFoot`.
struct ProjectLatelyRow: View {
    let item: ProjectItem
    let timeline: ProjectTimeline
    let state: ProjectState.Output
    let today: ISODay
    let selection: ProjectKey?
    let readerEpisode: String?
    let names: EntityNames
    let pick: (ProjectKey) -> Void
    let openEntity: (String) -> Void
    let showSource: (ProjectKey) -> Void
    let closeReader: () -> Void
    var withdraw: ((String) -> Void)? = nil
    var writesBlocked = false
    /// Owned by the column (one for every row), so Resume keeps one view model however many rows are built.
    let conversations: ConversationsViewModel

    @Environment(Store.self) private var store

    var body: some View {
        let key = ProjectKey.item(item.id)
        let selected = selection == key
        let evidence = ProjectSource.evidence(item)
        let target = ProjectSource.target(item, projectId: timeline.project.id)
        let showing = selected && readerEpisode != nil && readerEpisode == target?.episode
        let date = ProjectStory.rowDate(item, today: today)
        return HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            StoryGlyph(glyph: ProjectStory.glyph(item)).padding(.top, CicadaTheme.scaled(6))
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
                StorySentence(text: item.text, participants: item.participants, total: item.participantsTotal,
                              lead: item.kind == "happening", openEntity: openEntity)
                if let facts = ProjectStory.factsLine(item, names: names) {
                    Text(facts).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                if selected {
                    if let evidence { ProjectQuoteBlock(evidence: evidence) }
                    if let basis = ProjectStory.basis(item.dateBasis) {
                        Text(basis).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    actions
                }
                ProjectSourceLineView(line: ProjectSource.line(item), evidence: evidence,
                                      subjectId: item.claim?.subject ?? timeline.project.id, showing: showing,
                                      show: target == nil ? nil : { showing ? closeReader() : showSource(key) })
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            VStack(alignment: .trailing, spacing: CicadaTheme.scaled(2)) {
                Text(ProjectStory.status(item, state: state, today: today))
                    .font(CicadaTheme.metaMediumFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Text(date.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(date.help)
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    @ViewBuilder
    private var actions: some View {
        let resumable = item.conversation.flatMap { c in c.resumable ? c.id : nil }
        // "Not right" only where the server can find the claim (`ProjectTimeline.holds`): an owner-page event that
        // names the project is shown here but lives outside the tree.
        let withdrawable = item.kind == "happening" && withdraw != nil && timeline.holds(item.project)
        if resumable != nil || withdrawable {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let id = resumable, let c = item.conversation {
                    NeutralButton(title: Copy.Projects.resume, systemImage: "arrow.uturn.right", size: .compact,
                                  help: Copy.Projects.resumeHelp(OriginIconography.label(for: c.harness ?? c.origin ?? ""))) {
                        // R-PP26 — `POST /conversations/{id}/resume` only checks `isfile()`; a gone transcript says so.
                        Task { store.toast = await conversations.resume(id).toast }
                    }
                }
                if withdrawable, let withdraw {
                    TextButton(title: Copy.Projects.notRight, help: writesBlocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.notRightHelp) {
                        withdraw(item.id)
                    }
                    .disabled(writesBlocked)
                }
            }
        }
    }
}

/// Lately's foot: "Cicada started tracking this" — the `created` item, never a row.
struct ProjectLatelyFoot: View {
    let text: String

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            StoryGlyph(glyph: .history)
            Text(text)
        }
        .font(CicadaTheme.metaFont)
        .foregroundStyle(CicadaTheme.textTertiary)
        .padding(.horizontal, CicadaTheme.spacingMD)
    }
}

/// Coming up's milestones (R-PP22; Projects v3): the planned milestones by target, each with its diamond, name and
/// state in words; selected, how it moved (its chain, always open — never a fold, decision 17), its source and Rename.
/// `rows` is what the section shows (capped, or all in the full list). Task 5 passes `markDone`, `rename` and `add`;
/// `showsAddButton` false keeps only the field M and the menu open (the capped section draws no add row).
struct ProjectPlanSection: View {
    let timeline: ProjectTimeline
    let rows: [ProjectPlan.Row]
    let today: ISODay
    let selection: ProjectKey?
    let names: EntityNames
    let pick: (ProjectKey) -> Void
    let showSource: (ProjectKey) -> Void
    var showsAddButton = true
    var markDone: ((String) -> Void)? = nil
    var rename: ((String, String) -> Void)? = nil
    var add: ((String, String?) -> Void)? = nil
    /// Set by the M key, the menu and "No plan yet" to open the add field; this section clears it once open. Read on
    /// appear as well as on change, because the lazy story may build this section after the request (finding 1).
    var addPending: Binding<Bool> = .constant(false)
    var writesBlocked = false
    /// R-PP23 — true while Rename or Add a milestone is open, so the column's L / M / D stand aside (the Inbox's
    /// `field == nil` guard): a letter typed into these fields is the person's word, never a command.
    var onEditingChange: (Bool) -> Void = { _ in }

    @State private var renaming: String?
    @State private var renameText = ""
    @State private var adding = false
    @State private var newName = ""
    @State private var hasDate = false
    @State private var newDate = Date()
    @FocusState private var renameFocused: Bool
    @FocusState private var addFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(rows) { row in planRow(row).id(ProjectKey.milestone(row.id).id) }
            if add != nil { addRow }
        }
        .onAppear { openAddIfPending() }
        .onChange(of: addPending.wrappedValue) { _, _ in openAddIfPending() }
        .onChange(of: renaming != nil || adding) { _, editing in onEditingChange(editing) }
        // Collapsing Plan while Rename or Add is open removes this view before `adding`/`renaming` change, so the
        // column's `typing` would stay true and L · M · D would stop working (final review of G141 PJ-5).
        .onDisappear { onEditingChange(false) }
    }

    private func openAddIfPending() {
        guard addPending.wrappedValue, add != nil else { return }
        addPending.wrappedValue = false
        adding = true
        DispatchQueue.main.async { addFocused = true }
    }

    private func planRow(_ row: ProjectPlan.Row) -> some View {
        let m = row.milestone
        let key = ProjectKey.milestone(m.slug)
        let selected = selection == key
        let chain = ProjectPlan.chain(m, today: today)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                PlanDiamond(style: ProjectPlan.diamond(row))
                if renaming == m.slug, let rename {
                    TextField("", text: $renameText)
                        .focused($renameFocused)
                        .cicadaField(isFocused: renameFocused, prompt: Copy.Projects.milestoneName, isEmpty: renameText.isEmpty)
                        .onSubmit {
                            let name = renameText.trimmingCharacters(in: .whitespacesAndNewlines)
                            if !name.isEmpty, name != m.name { rename(m.slug, name) }
                            renaming = nil
                        }
                        .onExitCommand { renaming = nil }
                        .frame(maxWidth: CicadaTheme.scaled(280))
                } else {
                    Text(m.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                }
                Text(ProjectPlan.meta(row, onName: m.on.flatMap { names.name(for: $0) }, today: today))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                if chain.count > 1 && !selected {
                    Text(Copy.Projects.moved(chain.count - 1))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                Spacer(minLength: 0)
                if let markDone, ProjectPlan.canMarkDone(row) {
                    NeutralButton(title: Copy.Projects.markDone, size: .compact, isDisabled: writesBlocked,
                                  help: Copy.Projects.doneHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                        markDone(m.slug)
                    }
                }
            }
            if selected && chain.count > 1 {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    ForEach(Array(chain.enumerated()), id: \.offset) { i, line in
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Capsule()
                                .fill(i == chain.count - 1 ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                                .frame(width: CicadaTheme.scaled(10), height: 1.5)
                            Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                }
                .padding(.leading, CicadaTheme.scaled(26))
            }
            if selected {
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProjectSourceLineView(line: ProjectSource.line(m, conversations: timeline.conversations),
                                          evidence: m.chain.first?.evidence.first(where: \.isSpan),
                                          subjectId: m.chain.first?.subject ?? timeline.project.id, showing: false,
                                          show: ProjectSource.target(m, projectId: timeline.project.id) == nil
                                              ? nil : { showSource(key) })
                    if rename != nil, renaming != m.slug, !ProjectPlan.isPending(m) {
                        TextButton(title: Copy.Projects.rename, help: Copy.Projects.renameHelp) {
                            renameText = m.name
                            renaming = m.slug
                            DispatchQueue.main.async { renameFocused = true }
                        }
                        .disabled(writesBlocked)
                    }
                }
                .padding(.leading, CicadaTheme.scaled(26))
            }
        }
        .modifier(StoryRowSurface(selected: selected))
        .onTapGesture { pick(key) }
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    /// R-PP22 — a name, and a date only from a native picker (Python decides every date from words; the app has no
    /// second date grammar). Nothing relative is sent: the picker's day goes out as `YYYY-MM-DD` (R-PJ6).
    @ViewBuilder
    private var addRow: some View {
        if adding {
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField("", text: $newName)
                    .focused($addFocused)
                    .cicadaField(isFocused: addFocused, prompt: Copy.Projects.milestonePlaceholder, isEmpty: newName.isEmpty)
                    .onSubmit(submitAdd)
                    .onExitCommand { adding = false }
                    .accessibilityLabel(Copy.Projects.milestoneName)
                    .frame(maxWidth: CicadaTheme.scaled(320))
                if hasDate {
                    DatePicker("", selection: $newDate, in: Date()..., displayedComponents: .date)
                        .labelsHidden()
                        .datePickerStyle(.field)
                    TextButton(title: Copy.Projects.removeDate) { hasDate = false }
                } else {
                    TextButton(title: Copy.Projects.addDate) { hasDate = true }
                }
                Spacer(minLength: 0)
                TextButton(title: Copy.Projects.cancel) {
                    adding = false
                    newName = ""
                }
                NeutralButton(title: Copy.Projects.add, size: .compact,
                              isDisabled: writesBlocked || newName.trimmingCharacters(in: .whitespaces).isEmpty,
                              help: Copy.Projects.addMilestoneHelp,
                              disabledHelp: writesBlocked ? Copy.Projects.sleepRunningHelp : Copy.Projects.milestoneName) {
                    submitAdd()
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
        } else if showsAddButton {
            TextButton(title: Copy.Projects.addMilestone, keyHint: "M", help: Copy.Projects.addMilestoneHelp) {
                adding = true
                DispatchQueue.main.async { addFocused = true }
            }
            .disabled(writesBlocked)
            .padding(.leading, CicadaTheme.scaled(2))
        }
    }

    private func submitAdd() {
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !writesBlocked, let add else { return }
        add(name, hasDate ? ISODay.today(now: newDate).description : nil)
        newName = ""
        hasDate = false
        adding = false
    }
}
