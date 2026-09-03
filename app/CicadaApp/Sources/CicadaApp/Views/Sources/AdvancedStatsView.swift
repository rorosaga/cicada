import SwiftUI

/// Counts-only statistics behind the Sources page's Advanced toggle (G124).
/// Stub in this slice so the page builds; Task 4 of the G124 plan fills it
/// with memory writes, sleep runs, streak and the most-written / most-read
/// entities — never a price or a token count (the 2026-09-03 ruling).
struct AdvancedStatsView: View {
    var onSelectEntity: ((String) -> Void)?
    var body: some View { EmptyView() }
}
