import Foundation

/// Projects v2 (owner 2026-10-19) — the top of a project's detail answers four questions once each: what it is (the
/// header's one-liner), where it stands, what happened last and what's next. Pure: `today` is an argument, every day
/// word comes from `RelativeDay` (DR-58), and a missing fact says so in words, never a guess. Each line that points at a
/// row carries its key, so a click selects it on the band and unfolds the section that holds it (R-PP11).
struct ProjectSummary: Equatable {
    struct Line: Equatable {
        let text: String
        let key: ProjectKey?
    }

    let stands: String
    let last: Line?
    let next: Line?

    static func make(_ t: ProjectTimeline, state: ProjectState.Output, today: ISODay,
                     locale: Locale = .autoupdatingCurrent) -> ProjectSummary {
        let lastItem = t.items.first { $0.kind != "created" }
        return ProjectSummary(stands: stands(t, state: state, today: today, locale: locale),
                              last: lastItem.map { last($0, today: today, locale: locale) },
                              next: next(t, state: state, skipping: lastItem?.id, today: today, locale: locale))
    }

    /// "In motion · 1 of 4 milestones done", "Quiet 30 days · no plan yet", "Resting · last heard Mar 3, 2025".
    static func stands(_ t: ProjectTimeline, state: ProjectState.Output, today: ISODay,
                       locale: Locale = .autoupdatingCurrent) -> String {
        let last = ISODay(t.lastMomentDay)
        let plan = state.planned ? Copy.Projects.milestonesDone(state.progress) : Copy.Projects.noPlanYetLower
        switch state.section {
        case .inMotion:
            return Eyebrow.text(Copy.Projects.inMotionWord, plan)
        case .quiet:
            return Eyebrow.text(Copy.Projects.quietFor(days: last.map { today - $0 } ?? 0), plan)
        case .resting:
            let heard = last.map { Copy.Projects.resting(lastHeard: RelativeDay.absolute($0, today: today, locale: locale)) }
                ?? Copy.Projects.nothingHeard
            return state.planned ? Eyebrow.text(heard, plan) : heard
        }
    }

    /// The newest happening: "Yesterday · Bob got the arm to pick a part".
    static func last(_ item: ProjectItem, today: ISODay, locale: Locale = .autoupdatingCurrent) -> Line {
        let text = ISODay(item.day).map { Eyebrow.text(RelativeDay.phrase($0, today: today, locale: locale), item.text) }
            ?? item.text
        return Line(text: text, key: .item(item.id))
    }

    /// The next milestone ("First grasp · Oct 1, in 8 days"; overdue says since when, never red — DR-7), else the
    /// newest thread still going that Last did not already say, else nil ("Nothing planned").
    static func next(_ t: ProjectTimeline, state: ProjectState.Output, skipping lastId: String?, today: ISODay,
                     locale: Locale = .autoupdatingCurrent) -> Line? {
        if let slug = state.next, let m = t.milestones.first(where: { $0.slug == slug }) {
            guard let target = ISODay(m.target) else { return Line(text: m.name, key: .milestone(slug)) }
            let day = RelativeDay.absolute(target, today: today, locale: locale)
            let when = target < today ? Copy.Projects.overdueSinceLower(day)
                : Copy.Projects.dayAndDistance(day, RelativeDay.distance(target, today: today))
            return Line(text: Eyebrow.text(m.name, when), key: .milestone(slug))
        }
        let live = ProjectStory.nowThreads(t, state: state)
            .first { !state.isQuiet($0.claimId) && $0.claimId != lastId }
        return live.map { Line(text: Copy.Projects.stillGoingLine($0.text), key: .thread($0.claimId)) }
    }
}
