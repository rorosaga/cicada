import SwiftUI

/// R-PP13 — a section's head: its label (DR-20's `SectionLabel`) with a disclosure chevron, and — collapsed — what it
/// holds in words, so a closed section still says so (DR-39).
struct ProjectSectionHeader: View {
    let title: String
    let meta: String
    let isOpen: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 9, weight: .medium))
                    .rotationEffect(.degrees(isOpen ? 90 : 0))
                    .foregroundStyle(CicadaTheme.textTertiary)
                SectionLabel(title)
                if !isOpen, !meta.isEmpty {
                    Text(meta).font(CicadaTheme.captionFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            .frame(height: CicadaTheme.scaled(24))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .help(isOpen ? Copy.Projects.collapse : Copy.Projects.expand)
        .accessibilityAddTraits(.isHeader)
    }
}

/// Now (§6.3): the ongoing threads — heard-from first, then quiet — each with its line of days; a quiet one whose
/// follow-up waits in the Inbox links to that card (R-PP18). Under them, the Sleep queue's honest line (§6.1 layer 7).
/// Task 5 passes `settle`, which draws Done · Still going · Stopped.
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

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(ProjectStory.nowThreads(timeline, state: state)) { thread in
                row(thread).id(ProjectKey.thread(thread.claimId).id)
            }
            if timeline.now.threads.isEmpty {
                Text(ProjectStory.nowEmpty(timeline, today: today))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
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

/// Plan (R-PP22): the milestones by target, each with its diamond, name and state in words; "moved once ›" unfolds
/// its chain. Task 5 passes `markDone`, `rename` and `add`.
struct ProjectPlanSection: View {
    let timeline: ProjectTimeline
    let today: ISODay
    let selection: ProjectKey?
    let names: EntityNames
    let pick: (ProjectKey) -> Void
    let showSource: (ProjectKey) -> Void
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

    @State private var chainOpen: Set<String> = []
    @State private var renaming: String?
    @State private var renameText = ""
    @State private var adding = false
    @State private var newName = ""
    @State private var hasDate = false
    @State private var newDate = Date()
    @FocusState private var renameFocused: Bool
    @FocusState private var addFocused: Bool

    var body: some View {
        let rows = ProjectPlan.rows(timeline.milestones, today: today)
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if rows.isEmpty {
                Text(Copy.Projects.noPlan)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingMD)
            }
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
                    TextField(Copy.Projects.milestoneName, text: $renameText)
                        .textFieldStyle(.roundedBorder)
                        .focused($renameFocused)
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
                if chain.count > 1 {
                    Button {
                        if chainOpen.contains(m.slug) { chainOpen.remove(m.slug) } else { chainOpen.insert(m.slug) }
                    } label: {
                        HStack(spacing: CicadaTheme.scaled(3)) {
                            Text(Copy.Projects.moved(chain.count - 1))
                            Image(systemName: "chevron.right")
                                .rotationEffect(.degrees(chainOpen.contains(m.slug) ? 90 : 0))
                        }
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                    }
                    .buttonStyle(.cicadaPlain)
                }
                Spacer(minLength: 0)
                if let markDone, ProjectPlan.canMarkDone(row) {
                    NeutralButton(title: Copy.Projects.markDone, size: .compact, isDisabled: writesBlocked,
                                  help: Copy.Projects.doneHelp, disabledHelp: Copy.Projects.sleepRunningHelp) {
                        markDone(m.slug)
                    }
                }
            }
            if chainOpen.contains(m.slug) {
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
                TextField(Copy.Projects.milestonePlaceholder, text: $newName)
                    .textFieldStyle(.roundedBorder)
                    .focused($addFocused)
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
        } else {
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

/// Around this project (§6.4, the brief's labels): each group's pages as one-line rows — the type's dot, the name, its
/// role and one fact, when it was last mentioned. A page opens its card in the third column; a part of this project
/// opens as the project (R-PP17); a tool unfolds its spec claims, each with its chip and "Show in conversation ›"; a
/// name no page holds yet is greyed, "mentioned once, not a page yet" — the promotion rule made visible.
struct ProjectAroundSection: View {
    let cluster: ProjectCluster
    let today: ISODay
    let partial: Bool
    let openCard: String?
    let openEntity: (String) -> Void
    let openProject: (String) -> Void
    let openSource: (ReaderTarget) -> Void

    @State private var expanded: Set<String> = []
    @State private var specs: [String: [Claim]] = [:]

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(cluster.groups) { group in
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    SectionLabel(ProjectAround.label(group.label)).padding(.horizontal, CicadaTheme.scaled(10))
                    ForEach(group.members) { member in
                        memberRow(member, opensProject: ProjectAround.opensProject(group))
                    }
                    if group.more > 0 {
                        Text(Copy.Projects.moreMembers(group.more))
                            .font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                            .padding(.horizontal, CicadaTheme.scaled(10))
                    }
                }
            }
            if !cluster.alsoUses.isEmpty {
                Text(Copy.Projects.alsoUses(cluster.alsoUses.map(\.name)))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
            if partial {
                Text(Copy.Projects.aroundIndexing)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.scaled(10))
            }
        }
    }

    @ViewBuilder
    private func memberRow(_ m: ProjectMember, opensProject: Bool) -> some View {
        if let id = m.memberId, !m.pending {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TypeDot(type: m.type)
                    Text(m.name).font(CicadaTheme.rowFont).foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if !m.rolePhrase.isEmpty {
                        Text(m.rolePhrase).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    }
                    if !m.fact.isEmpty {
                        Text(m.fact).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    if let last = ProjectAround.last(m, today: today) {
                        Text(last.text).font(CicadaTheme.metaFont).monospacedDigit()
                            .foregroundStyle(CicadaTheme.textTertiary).help(last.help)
                    }
                    if ProjectAround.expands(m) {
                        IconButton(systemName: expanded.contains(id) ? "chevron.down" : "chevron.right",
                                   help: expanded.contains(id) ? Copy.Projects.hideSpecs(m.name) : Copy.Projects.showSpecs(m.name)) {
                            toggle(id)
                        }
                    }
                }
                .listRowSurface(height: RowMetrics.oneLine, selected: openCard == id)
                .onTapGesture { opensProject ? openProject(id) : openEntity(id) }
                .accessibilityElement(children: .contain)
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(Copy.Projects.openEntity(m.name, type: m.type.label))
                if expanded.contains(id) { specsView(id) }
            }
        } else {
            HStack(spacing: CicadaTheme.spacingSM) {
                Circle().strokeBorder(CicadaTheme.textTertiary, lineWidth: 1.5)
                    .frame(width: CicadaTheme.scaled(8), height: CicadaTheme.scaled(8))
                Text(m.name).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textTertiary)
                Text(Copy.Projects.notAPageYet).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
            .frame(height: CicadaTheme.scaled(RowMetrics.oneLine))
            .help(Copy.Projects.notAPageYetHelp)
        }
    }

    @ViewBuilder
    private func specsView(_ id: String) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let claims = specs[id] {
                if claims.isEmpty {
                    Text(Copy.Projects.noSpecs).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                ForEach(claims) { claim in
                    let chips = EvidenceChipModel.chips(evidence: claim.evidence, sourceEpisodes: claim.sourceEpisodes,
                                                        subjectId: id)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(claim.text).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                        if let chip = chips.first { EvidenceChip(model: chip, subjectId: id) }
                        Spacer(minLength: 0)
                        if let target = chips.first?.target(subjectId: id, meta: nil) {
                            InlineLink(title: Copy.Projects.showInConversation, help: Copy.Projects.showHelp) {
                                openSource(target)
                            }
                        }
                    }
                }
            } else {
                Text(Copy.Projects.readingCard).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(.leading, CicadaTheme.scaled(28))
        .padding(.vertical, CicadaTheme.spacingXS)
    }

    private func toggle(_ id: String) {
        if expanded.contains(id) {
            expanded.remove(id)
            return
        }
        expanded.insert(id)
        guard specs[id] == nil else { return }
        Task {
            let claims = (try? await APIClient.shared.fetchClaims(subject: id)) ?? []
            specs[id] = ProjectAround.specs(claims)
        }
    }
}
