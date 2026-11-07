import SwiftUI

/// Everything under the room, as one centred group in the 760 pt text column (DR-36; 2026-10-16, the owner's live
/// capture during a run: "those stages of reading and stuff are kind of ugly … center it").
///
/// Top to bottom, every row centred on the column's axis and nothing left-aligned:
/// 1. **the sentence** — the lead and its one secondary line (`RoomSentenceView`);
/// 2. **the control group** — Consolidate, Pause, Cancel or Continue with the engine menu, the stop's whisper on its
///    own line under them (`SleepControlRow`);
/// 3. **the notes** — the first save's link, the automatic continue's promise, a finished run's parked line;
/// 4. **the schedule** — the lamp's twin in words;
/// 5. **the instrument** — the stage stepper and the progress bar at the column's full width, one over the other,
///    the counts centred under the bar (`RunInstrument`).
///
/// Each thing is said once: the running stage's name is the lead ("Filing…") and the stepper's current step, its
/// purpose is the secondary line, and what a stop does while it files is the whisper under the controls.
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
    /// ROR-118 round 2 - "last read 2 h ago", said in the lamp's line beside the room (nil: not said).
    var lastRead: String? = nil
    /// ROR-118 round 6 - beside the room the block is laid out to the room's own height: the page's title on top, the
    /// headline and its lamp line in the middle, the buttons last, the free height shared by two springs, so the block's
    /// top and bottom edges are the room's whatever the state says (`fillHeight`). The run's instrument is then drawn
    /// by the page under both, at full width, never inside a block whose height the room sets.
    var title: AnyView? = nil
    var fillHeight: CGFloat? = nil
    /// ROR-118 round 6 - only the notes (the first save's link, the automatic continue's promise, parked conversations),
    /// drawn by the page under the room's row so the block beside the room never grows past the room.
    var notesOnly = false

    var body: some View {
        if notesOnly { notes.padding(.top, CicadaTheme.spacingSM).frame(maxWidth: .infinity, alignment: .leading) }
        else if leading, let fillHeight { pinned(height: fillHeight) } else { stacked }
    }

    private func pinned(height: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            title
            Spacer(minLength: CicadaTheme.spacingMD)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                RoomSentenceView(line: status, answers: answers, room: room, feedAsleep: feedAsleep, perform: perform,
                                 leading: true)
                whisperRow.accessibilitySortPriority(RoomA11yOrder.whisper)
            }
            Spacer(minLength: CicadaTheme.spacingMD)
            SleepControlRow(consolidateEnabled: page.consolidateEnabled, queuedCount: page.queuedCount, page: page,
                            leading: true, part: .buttons)
                .accessibilitySortPriority(RoomA11yOrder.control)
                .tourAnchor(.consolidate)
        }
        .frame(maxWidth: SleepLayout.contentWidth, minHeight: height, alignment: .top)
    }

    private var stacked: some View {
        VStack(alignment: leading ? .leading : .center, spacing: CicadaTheme.spacingMD) {
            // R-Z5 — the one slot the worm speaks in; an answer replaces the status here (R-Z7).
            RoomSentenceView(line: status, answers: answers, room: room, feedAsleep: feedAsleep, perform: perform,
                             leading: leading)
            // ROR-118 round 5 - beside the room the schedule is the one fact about the job, so it sits under the
            // headline it explains (overdue because no schedule), not under the buttons.
            if leading { whisperRow.accessibilitySortPriority(RoomA11yOrder.whisper) }
            SleepControlRow(consolidateEnabled: page.consolidateEnabled, queuedCount: page.queuedCount, page: page,
                            leading: leading)
                .accessibilitySortPriority(RoomA11yOrder.control)
                .tourAnchor(.consolidate)
            notes
            if !leading { whisperRow.accessibilitySortPriority(RoomA11yOrder.whisper) }
            RunInstrument(page: page, justFinished: room.recentCycleCommit != nil)
        }
        .frame(maxWidth: SleepLayout.contentWidth)
    }

    /// Sleep page v5 — the lines under the controls: the first save's link to the person's own page, the automatic
    /// continue's promise (ruling 15, in words), and a finished run's parked conversations (a link to Waiting).
    @ViewBuilder
    private var notes: some View {
        if page.isRunning, let drain = page.drain, drain.firstRun == true, drain.committedBatches == 1,
           drain.ownerPage != nil, let owner = ownerEntityId {
            InlineLink(title: Copy.SleepV5.seeYourPage) { onSelectEntity?(owner) }
        }
        if let when = page.autoContinueWhen, page.paused != nil {
            Text(Copy.SleepV5.willContinueBySelf(when))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(leading ? .leading : .center)
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

    /// The schedule in one quiet line (§7.2) — the lamp's text twin (R-A3). Since Z6 it is a control: it opens the
    /// same `LampPopover` the lamp does, anchored here (Z-P25); the popover's engine line shows the scheduled engine
    /// ALWAYS, so ruling 4 is on screen at the moment someone chooses to schedule.
    @ViewBuilder
    private var whisperRow: some View {
        // The switch is the lamp's second door (owner 2026-11-07), beside the sentence that says whether it is on.
        HStack(spacing: CicadaTheme.spacingSM) {
            if leading { cornerWhisper } else { centredWhisper }
            LampSwitch()
        }
        .frame(maxWidth: .infinity, alignment: leading ? .leading : .center)
    }

    /// ROR-118 round 4 - beside the room the schedule is the one fact about the job, so it is a quiet 13 pt
    /// button (DR-40), the headline's subtitle, never a 12 pt caption under the buttons.
    private var cornerWhisper: some View {
        NeutralButton(title: cornerWhisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText,
                                               lampLit: page.lampLit, lastRead: lastRead),
                      systemImage: "moon.zzz", size: .compact,
                      help: page.nextRunText.hasSuffix("—") ? Copy.nextRunUnknownReason : Copy.lampHint, quiet: true) {
            room.lampPopover = .whisper
        }
        .roomLinkCursor()
        .accessibilityHint(Copy.lampHint)
        .popover(isPresented: Binding(get: { room.lampPopover == .whisper },
                                      set: { if !$0 { room.lampPopover = nil } }),
                 arrowEdge: .bottom) { LampPopover(page: page) }
        .padding(.leading, -CicadaTheme.scaled(10))   // the words hang on the headline's left edge, not the button's padding
        .padding(.top, -CicadaTheme.spacingXS)
    }

    private var centredWhisper: some View {
        Button { room.lampPopover = .whisper } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "moon.zzz")
                    .font(CicadaTheme.font(size: 11))
                    .iconHover()
                Text(leading
                     ? cornerWhisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText,
                                         lampLit: page.lampLit, lastRead: lastRead)
                     : whisperLine(scheduleText: page.scheduleText, nextRunText: page.nextRunText,
                                   lampLit: page.lampLit))
                    .font(CicadaTheme.captionFont)
            }
            .foregroundStyle(leading ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
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

/// The run's instrument at the foot of the room's column: the stage stepper and the progress bar, the same width (the
/// column's), one over the other, so they read as one gauge rather than three widths stacked (2026-10-16).
///
/// The stepper shows while a cycle runs and as the frozen record after a cancel or failure (R-Z6, P15); the bar while
/// a run reads in batches, while it waits paused, and in the moment it finished (the "See what changed" window) —
/// never a remaining time (G107). Nothing here when neither has news.
struct RunInstrument: View {
    let page: SleepPageModel
    /// A completion is on show (`RoomModel.recentCycleCommit`): the bar keeps the run's final counts.
    var justFinished = false

    var showsStepper: Bool {
        stageStripIsVisible(isRunning: page.isRunning, cancelled: page.stoppedEarly, failed: page.cycleError != nil)
    }

    var progress: RunProgress? {
        guard let progress = RunProgress.from(page.drain),
              page.isRunning || page.paused != nil || justFinished else { return nil }
        return progress
    }

    var body: some View {
        let progress = progress
        if showsStepper || progress != nil {
            VStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
                if showsStepper {
                    SleepStageStrip(pips: page.pips)
                    if let note = batchFailureNote(drain: page.drain, activeStage: page.runningStage) {
                        RunFailureNote(text: note)
                    }
                }
                if let progress { RunProgressBar(progress: progress) }
            }
            .frame(maxWidth: .infinity)
            // A little more air above the gauge than between the lines of words: it is a second group.
            .padding(.top, CicadaTheme.spacingSM)
        }
    }
}
