import SwiftUI

// MARK: - The titlebar's ? (R-DS18)

/// Which popover the titlebar's `?` opens — Sleep explains how Cicada sleeps, every other page
/// what Cicada is (R-DS18). Track P: the audit removed the Sleep and Upload buttons from every
/// page (R1), so "About these actions" no longer had any actions to describe — `.actions`
/// became `.aboutCicada`, one paragraph per half of Awake/Sleep, true on every page it renders
/// on. The Sleep page keeps its own page-specific explainer (G125 R10); the list pages answer for
/// themselves — the Inbox (R-DI17, DR-25), then Clusters (R-DL8), then the Feed, then Sources, then
/// Projects — with their subtitle and key map,
/// since the eyebrow row that replaced each page header has no room for either; and the Graph its keys and gestures
/// (R-DG6), which nothing on a canvas explains otherwise.
enum HelpContent: Equatable {
    case aboutCicada
    case howSleepWorks
    case inbox
    case graph
    case clusters
    case feed
    case sources
    case projects

    static func page(_ tab: AppTab) -> HelpContent {
        switch tab {
        case .sleep: .howSleepWorks
        case .inbox: .inbox
        case .graph: .graph
        case .clusters: .clusters
        case .feed: .feed
        case .sources: .sources
        case .projects: .projects
        default: .aboutCicada
        }
    }
}

/// The page's `?` — the titlebar's rightmost control, one per window, answering for the visible
/// page (DR-23, Track P). It replaced a `TopBarControls` floated by four pages at four slightly
/// different offsets.
struct TitlebarHelpButton: View {
    let content: HelpContent
    @State private var showing = false

    var body: some View {
        IconButton(systemName: "questionmark.circle", help: Copy.helpForThisPage, size: .titlebar) { showing.toggle() }
            .popover(isPresented: $showing, arrowEdge: .bottom) {
                switch content {
                case .aboutCicada: AboutCicadaPopover()
                case .howSleepWorks: HowSleepWorksContent()
                case .inbox: InboxHelpPopover()
                case .graph: GraphHelpPopover()
                case .clusters: ListHelpPopover(page: ListHelp.clusters)
                case .feed: ListHelpPopover(page: ListHelp.feed)
                case .sources: ListHelpPopover(page: ListHelp.sources)
                case .projects: ListHelpPopover(page: ListHelp.projects)
                }
            }
    }
}

// MARK: - The Inbox's ?

/// R-DI17 / DR-25 — the Inbox's `?`: the subtitle the page no longer prints, and the keys that act on
/// it, each with its pointer twin on the page (DR-49, DR-68).
enum InboxHelp {
    struct Key: Equatable { let key: String; let does: String }
    static let keys: [Key] = [
        .init(key: "1–9", does: "Answer with an option"),
        .init(key: "↑ ↓", does: "Move through the questions, or the answers"),
        .init(key: "⏎", does: "Answer with the highlighted option"),
        .init(key: "O", does: "Other… — say what's actually true"),
        .init(key: "L", does: "Not now — ask again in 7 days"),
        .init(key: "⌘Z", does: "Undo the last answer"),
        .init(key: "Esc", does: "Close Other…, then the rightmost column"),
        .init(key: "Tab", does: "Move between the list, the question and the conversation"),
    ]
}

struct InboxHelpPopover: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SectionLabel("How the inbox works")
            Text(Copy.inboxSubtitle).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary)
            ForEach(InboxHelp.keys, id: \.key) { k in
                HStack(spacing: CicadaTheme.spacingSM) {
                    KeyHint(k.key).frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                    Text(k.does).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: CicadaTheme.scaled(340))
        .background(CicadaTheme.bgMenu)
    }
}

// MARK: - The list pages' ? (R-DL8, DR-25)

/// A list page's `?`: the subtitle its eyebrow row has no room for, and the keys that act on it, each with its pointer
/// twin on the page (DR-49, DR-68).
enum ListHelp {
    struct Page: Equatable {
        let title: String
        let subtitle: String
        let keys: [InboxHelp.Key]
    }

    static let clusters = Page(
        title: "How Clusters works",
        subtitle: "Every entity, grouped by type. Pick a type, open a card, then follow a belief to the conversation it came from.",
        keys: [
            .init(key: "⌘F", does: "Find on this page"),
            .init(key: "↑ ↓", does: "Move through the list"),
            .init(key: "⏎", does: "Step into the card"),
            .init(key: "⌘[", does: "Back to the previous card"),
            .init(key: "Esc", does: "Close the rightmost column"),
        ])

    static let feed = Page(
        title: "How the Feed works",
        subtitle: "Everything Cicada has read. Open an item to see why it was saved and where it came from; + adds a source.",
        keys: [
            .init(key: "⌘N", does: "Add a source"),
            .init(key: "⌘F", does: "Find on this page"),
            .init(key: "↑ ↓", does: "Move through the list"),
            .init(key: "⏎", does: "Step into the item"),
            .init(key: "Esc", does: "Close the rightmost column"),
        ])

    static let sources = Page(
        title: "How Sources works",
        subtitle: "Where your memory comes from, and who wrote it. Open a source to see what it brought in.",
        keys: [
            .init(key: "⌘F", does: "Filter a source's conversations by title"),
            .init(key: "↑ ↓", does: "Move through the sources"),
            .init(key: "⌘[", does: "Back to all sources"),
            .init(key: "⌥↑ ⌥↓", does: "Previous or next citation"),
            .init(key: "Esc", does: "Close the Reader, then the source"),
        ])

    /// G141 PJ-5 — the Projects page's `?`: what the band means, and its keys (DR-68). Task 3 adds the band's keys and
    /// Task 5 the Log's, each with the code that answers them.
    static let projects = Page(
        title: "How Projects works",
        subtitle: "Where each project stands today: a green bar that fills up to today, what's in motion, what happened lately and what's planned. Open a project to see the rest. Every mark on the bar opens what it stands for.",
        keys: [
            .init(key: "⌘F", does: "Find on this page"),
            .init(key: "↑ ↓", does: "Move through projects"),
            .init(key: "⏎", does: "Step into the project"),
            .init(key: "← →", does: "Step along the bar; ⏎ shows it in the conversation"),
            .init(key: "L", does: "Log progress"),
            .init(key: "M", does: "Add a milestone"),
            .init(key: "D", does: "Mark the selected thread or milestone done"),
            .init(key: "Esc", does: "Close the rightmost column"),
        ])
}

struct ListHelpPopover: View {
    let page: ListHelp.Page

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SectionLabel(page.title)
            Text(page.subtitle).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(page.keys, id: \.key) { k in
                HStack(spacing: CicadaTheme.spacingSM) {
                    KeyHint(k.key).frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                    Text(k.does).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: CicadaTheme.scaled(340))
        .background(CicadaTheme.bgMenu)
    }
}

// MARK: - About Cicada Popover

/// The titlebar `?`'s popover on every page but Sleep (R-DS18). Track P rewrote it: the old
/// two rows described the Sleep and Upload buttons this audit deleted, and
/// both sentences were false anyway — capture was pitched as something MCP
/// clients do (G105 replaced that with the harness's own Stop hook, which
/// cannot be skipped by a model declining to call a tool), and consolidation
/// was described as automatic when a fresh install's schedule is `manual`.
/// The two rows now name the two halves of Awake/Sleep instead of two
/// buttons, so the popover stays true on every page that renders it.
struct AboutCicadaPopover: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            SectionLabel("About Cicada")

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .font(CicadaTheme.font(size: 14))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Capture")
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text(Copy.aboutCicadaCapture)
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                Image(systemName: "moon.fill")
                    .font(CicadaTheme.font(size: 14))
                    // DR-5: the accent is never decorative.
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Sleep")
                        .font(CicadaTheme.font(size: 13, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)

                    Text(Copy.aboutCicadaSleep)
                        .font(CicadaTheme.font(size: 11))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: 340)
        .background(CicadaTheme.surface)
    }
}

// MARK: - The Graph's ?

/// R-DG6 — the canvas's keys and gestures in words (DR-69): nothing on a canvas explains itself.
enum GraphHelp {
    struct Key: Equatable { let key: String; let does: String }
    static let keys: [Key] = [
        .init(key: "⌘F", does: "Find a node on the canvas"),
        .init(key: "⌘K", does: "Search all of your memory"),
        .init(key: "Esc", does: "Close find, the legend, the conversation, then the page — one at a time"),
        .init(key: "⌘[", does: "Back to the page you came from"),
        .init(key: "Shift", does: "Hold to pan, or turn on the pan button"),
    ]
    static let gestures: [Key] = [
        .init(key: "Double-click", does: "Focus a node and its neighbours"),
        .init(key: "Click empty space", does: "Close the page that's open"),
    ]
}

struct GraphHelpPopover: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SectionLabel(Copy.Graph.helpTitle)
            ForEach(GraphHelp.keys, id: \.key) { k in
                HStack(spacing: CicadaTheme.spacingSM) {
                    KeyHint(k.key).frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                    Text(k.does).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            ForEach(GraphHelp.gestures, id: \.key) { g in
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(g.key).font(CicadaTheme.metaMediumFont).foregroundStyle(CicadaTheme.textPrimary)
                        .frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                    Text(g.does).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(width: CicadaTheme.scaled(360))
        .background(CicadaTheme.bgMenu)
    }
}
