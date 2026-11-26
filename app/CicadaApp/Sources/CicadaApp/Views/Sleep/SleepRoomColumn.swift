import SwiftUI

/// Everything beside (or, in a narrow column, under) the room: the sentence slot, the control group, the notes.
///
/// Top to bottom:
/// 1. **the status slot** — the status chip and its one secondary line, or, while a run is on the page, the run's one
///    quiet object (`RunObjectView`, 2026-11-26): the step in a word, the run's own count, one bar, at most one note;
/// 2. **the control group** — Consolidate, Pause, Cancel or Continue with the engine, the schedule (`SleepControlRow`);
/// 3. **the notes** — a refused night's quiet line, the automatic continue's promise, a finished run's parked line.
///
/// The stage stepper, the legend under the bar, the elapsed caption and the stop's whisper under the controls retired
/// with that redesign: each is the object's `.help` or its one note, said once (DR-38).
///
/// A view of its own (it was a stretch of `SleepView.roomBlock`) so `SleepRunStripTests` can lay it out offscreen in
/// every run state, at both window widths and in both themes, without a running page around it.
struct SleepRoomColumn: View {
    let page: SleepPageModel
    let status: SentenceLine
    let answers: [SentenceLine]
    let room: RoomModel
    var feedAsleep = false
    var perform: (SentenceAction) -> Void = { _ in }
    /// The owner's page id (G117) — `nil` until the graph has loaded.
    var ownerEntityId: String? = nil
    var onSelectEntity: ((String) -> Void)? = nil
    var openDetails: (DetailsSection) -> Void = { _ in }
    /// ROR-118 — the page sets the group on the leading edge, beside the room's rectangle (DR-36 amended in §9); the
    /// offscreen layouts keep the centred column.
    var leading = false
    /// ROR-118 round 6 - beside the room the block is laid out to the room's own height: the page's title on top (the
    /// name, when Sleep last read, and the machines), the status slot in the middle (the run's one object while a run is
    /// on the page, 2026-11-26), the run bar last (2026-11-24: the engine, the schedule and the one primary as one
    /// object), the free height shared by two springs, so the block's top and bottom edges are the room's whatever the
    /// state says (`fillHeight`); while a run is on the page the object hangs from the title at one fixed offset and the
    /// free height is one spring above the run bar, so the word and the bar never move between run states. Nothing about a run hangs under the pair any more, so nothing below it moves when a
    /// run starts or ends.
    var title: AnyView? = nil
    var fillHeight: CGFloat? = nil
    /// ROR-118 round 6 - only the notes (a refused night's line, the automatic continue's promise, parked conversations),
    /// drawn by the page under the room's row so the block beside the room never grows past the room.
    var notesOnly = false

    var body: some View {
        if notesOnly { notes.padding(.top, CicadaTheme.spacingSM).frame(maxWidth: .infinity, alignment: .leading) }
        else if leading, let fillHeight { pinned(height: fillHeight) } else { stacked }
    }

    private func pinned(height: CGFloat) -> some View {
        // At 2 pt a cell the block is 128 pt: the run object's gaps tighten so a note still fits inside it.
        let compact = height < CicadaTheme.scaled(160)
        return VStack(alignment: .leading, spacing: 0) {
            title
            if run != nil {
                // A run's object hangs from the title at one fixed offset, whatever it carries: the word and the bar
                // sit at the same height in reading, filing, paused, stopped, failed and finished, and a note appears
                // in the room under the bar instead of moving them. The block ends where the room does (`fillHeight`).
                // Beside the 192 pt room the offset leaves about as much air over the word as under a note.
                Spacer().frame(height: compact ? CicadaTheme.spacingSM : CicadaTheme.spacingXL)
                statusSlot(leading: true, compact: compact)
                Spacer(minLength: compact ? CicadaTheme.spacingXS : CicadaTheme.spacingSM)
            } else {
                Spacer(minLength: CicadaTheme.spacingSM)
                statusSlot(leading: true)
                Spacer(minLength: CicadaTheme.spacingSM)
            }
            SleepControlRow(consolidateEnabled: page.consolidateEnabled, queuedCount: page.queuedCount, page: page,
                            leading: true, part: .buttons, room: room)
                .accessibilitySortPriority(RoomA11yOrder.control)
                .tourAnchor(.consolidate)
        }
        .frame(maxWidth: SleepLayout.contentWidth, minHeight: height, alignment: .top)
    }

    private var stacked: some View {
        VStack(alignment: leading ? .leading : .center, spacing: CicadaTheme.spacingMD) {
            // R-Z5 — the one slot the worm speaks in; an answer replaces the status here (R-Z7).
            statusSlot(leading: leading)
            // Leading (the page's own layout, below 720 pt of column): the run bar, which holds the schedule.
            SleepControlRow(consolidateEnabled: page.consolidateEnabled, queuedCount: page.queuedCount, page: page,
                            leading: leading, room: room)
                .accessibilitySortPriority(RoomA11yOrder.control)
                .tourAnchor(.consolidate)
            notes
            if !leading { centredWhisper.accessibilitySortPriority(RoomA11yOrder.whisper) }
        }
        .frame(maxWidth: SleepLayout.contentWidth)
    }

    /// The run on the page, if there is one (`RunLine.from`): the first run's link to the person's own page rides it.
    private var run: RunLine? {
        RunLine.from(page, recentCycleCommit: room.recentCycleCommit, canOpenOwnerPage: ownerEntityId != nil)
    }

    /// The one slot the page's state speaks in (R-Z5): the status sentence, or the run's object while a run is on the
    /// page. An answer from the worm or a feed line still replaces either.
    private func statusSlot(leading: Bool, compact: Bool = false) -> some View {
        RoomSentenceView(line: status, answers: answers, room: room, feedAsleep: feedAsleep, perform: perform,
                         leading: leading, run: run, compactRun: compact,
                         openOwnerPage: { ownerEntityId.map { onSelectEntity?($0) } })
    }

    /// The lines under the controls: a refused night's quiet line and a finished run's parked conversations (a link to
    /// Waiting). The first save's link and the automatic continue's promise (ruling 15, in the pause's own words) ride
    /// the run's object since 2026-11-26.
    @ViewBuilder
    private var notes: some View {
        // 2026-11-26 — a scheduled run the write window refused before it read: one quiet line, never the error
        // state (nothing was read, used or broken). The backend's own words; its full sentence is the help.
        if let notice = page.notice {
            Text(notice.text)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(leading ? .leading : .center)
                .help(notice.detail)
                .accessibilityHint(notice.detail)
        }
        if !page.isRunning, page.paused == nil, page.parkedCount > 0 {
            Button { openDetails(.waiting) } label: {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundStyle(CicadaTheme.warning)
                        .accessibilityHidden(true)
                    Text(Copy.SleepV5.parkedLine(page.parkedCount))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .font(CicadaTheme.captionFont)
            }
            .buttonStyle(.cicadaPlain)
        }
    }

    /// The schedule in one quiet line (§7.2) — the lamp's text twin (R-A3), in the centred group only; beside the room
    /// the run bar holds the schedule. Since Z6 it is a control: it opens the same `LampPopover` the lamp does,
    /// anchored here (Z-P25); the popover's engine line shows the scheduled engine ALWAYS, so ruling 4 is on screen at
    /// the moment someone chooses to schedule.
    private var centredWhisper: some View {
        // The switch is the lamp's second door (owner 2026-11-07), beside the sentence that says whether it is on.
        HStack(spacing: CicadaTheme.spacingSM) {
            centredWhisperButton
            LampSwitch()
        }
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private var centredWhisperButton: some View {
        Button { room.lampPopover = .whisper } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "moon.zzz")
                    .font(CicadaTheme.font(size: 11))
                    .iconHover()
                Text(whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText, lampLit: page.lampLit))
                    .font(CicadaTheme.captionFont)
            }
            .foregroundStyle(CicadaTheme.textTertiary)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .roomLinkCursor()
        // R-A14 — "Next run —" is a value with a reason; an empty help
        // string renders no tooltip, so a real time carries none.
        .help(page.nextRunText.hasSuffix("—") ? Copy.nextRunUnknownReason : "")
        .accessibilityHint(Copy.lampHint)
        .popover(isPresented: Binding(get: { room.lampPopover == .whisper },
                                      set: { if !$0 { room.lampPopover = nil } }),
                 arrowEdge: .bottom) { LampPopover(page: page) }
    }
}
