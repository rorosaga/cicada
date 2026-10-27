import SwiftUI

/// Ruling 45 / proposal §2.5 — the Done fold: what finished, newest first — closed happenings, milestones marked done,
/// backlog items done and decisions taken (a moment whose facts say "decided" or "chose"). No new writer: everything
/// comes from what `g141-7` and the backlog read already send.
struct ProjectDoneEntry: Identifiable, Equatable {
    enum Kind: String { case happening, milestone, backlog, decision }
    let id: String
    let kind: Kind
    let text: String
    let day: String?
}

enum ProjectDone {
    /// Shown before "Show all n".
    static let shown = 3
    private static let decisionWords = ["decided", "chose", "decides", "chooses"]

    static func entries(_ t: ProjectTimeline, backlog: BacklogList?) -> [ProjectDoneEntry] {
        var out: [ProjectDoneEntry] = []
        for item in t.items where item.kind == "happening" && item.state == "done" {
            out.append(.init(id: "h:\(item.id)", kind: .happening, text: item.text, day: item.day))
        }
        for m in t.milestones where m.status == "done" {
            out.append(.init(id: "m:\(m.slug)", kind: .milestone, text: m.name, day: m.doneOn))
        }
        for item in t.items where item.kind == "moment"
            && item.facts.contains(where: { f in decisionWords.contains { f.phrase.lowercased().contains($0) } }) {
            out.append(.init(id: "d:\(item.id)", kind: .decision, text: item.text, day: item.day))
        }
        for b in backlog?.items ?? [] where b.status == "done" {
            out.append(.init(id: "b:\(b.id)", kind: .backlog, text: b.title, day: String(b.updated.prefix(10))))
        }
        return out.sorted { ($0.day ?? "", $0.id) > ($1.day ?? "", $1.id) }
    }
}

/// The fold's body: the newest three, then "Show all n" (DR-39's quiet growth).
struct ProjectDoneSection: View {
    let entries: [ProjectDoneEntry]
    @State private var showAll = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(6)) {
            if entries.isEmpty {
                Text(Copy.ProjectsMine.nothingDone)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(showAll ? entries : Array(entries.prefix(ProjectDone.shown))) { e in
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Image(systemName: glyph(e.kind))
                        .font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text(e.text)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if let day = Copy.ProjectsMine.day(e.day) {
                        Text(day).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
                .accessibilityElement(children: .combine)
            }
            if entries.count > ProjectDone.shown {
                TextButton(title: showAll ? Copy.ProjectsMine.showFewer : Copy.ProjectsMine.showAll(entries.count),
                           action: { showAll.toggle() })
            }
        }
    }

    private func glyph(_ kind: ProjectDoneEntry.Kind) -> String {
        switch kind {
        case .happening: return "checkmark"
        case .milestone: return "diamond"
        case .backlog: return "tray"
        case .decision: return "arrow.triangle.branch"
        }
    }
}
