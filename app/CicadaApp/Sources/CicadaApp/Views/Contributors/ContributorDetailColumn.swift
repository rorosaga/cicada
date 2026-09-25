import SwiftUI

/// R-DL22 — a contributor's drill-down as Sources' detail column, not a sheet: a sheet hid the Reader its own "from
/// conversation" opens (the rule the Ask and Timeline sheets follow by stepping aside). `ContributorDrillDown` itself
/// is unchanged; it moved. The full `Cicada-Author` value stays one hover away (E3).
struct ContributorDetailColumn: View {
    let contributor: Contributor
    let share: Double?
    var hiddenListCount: Int? = nil
    var onShowList: () -> Void = {}
    let onClose: () -> Void

    var body: some View {
        let kind = ContributorIdentity.kind(of: contributor)
        VStack(alignment: .leading, spacing: 0) {
            DetailHeader(title: ContributorIdentity.displayName(author: contributor.author, kind: kind),
                         blurb: Copy.Lists.contributorBlurb(commits: contributor.commitCount, share: share),
                         backLabel: hiddenListCount.map(Copy.Lists.sourcesBack), onShowList: onShowList,
                         closeHelp: Copy.Lists.closeSource,
                         closeShortcut: KeyboardShortcut("[", modifiers: .command), onClose: onClose) {
                ContributorAvatar(contributor: contributor, kind: kind, size: CicadaTheme.scaled(20))
            }
            .help(contributor.author)
            ScrollView {
                ContributorDrillDown(contributor: contributor)
                    .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, alignment: .top)
    }
}
