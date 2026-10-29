import SwiftUI

/// G227 (owner 2026-10-29: "Ideally it should be like a tag … I guess the parenthesis is not really needed") — when
/// another page shares a title, the plain name is followed by its qualifier as the one pill, `Tag` (DR-44): quiet,
/// never a filter, never mono. Nothing when the title is the page's own. Running text (a sentence, a tooltip, VoiceOver,
/// a dialog button) keeps "<name> (<qualifier>)" — a sentence cannot hold a pill (DESIGN_RULES §9, 2026-10-29).
struct QualifierTag: View {
    let qualifier: String?

    var body: some View {
        if let qualifier, !qualifier.isEmpty {
            Tag(text: qualifier)
                .help(Copy.Graph.qualifierHelp)
                .fixedSize()
        }
    }
}
