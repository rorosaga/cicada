import SwiftUI

// G67 — the shared commit-diff renderer.
//
// One component, two call sites: the entity detail card's History tab (a tapped
// commit row expands into it) and the Contributors drill-down (a tapped entity
// chip on a commit). The parsing/ordering/gutter decisions live in `DiffModel`
// so they are testable without a view hierarchy; `DiffView` only paints.
//
// The backend hands us two newline-joined blocks (`added` / `removed`) produced
// from `git show --unified=0`, so the original interleaving is already lost.
// We render removals first, then additions — the same order the old inline
// renderer used, and the order a reader expects for "what this commit changed".

/// One rendered diff row.
struct DiffLine: Identifiable, Equatable {
    enum Kind: Equatable {
        case removed
        case added
        /// The backend's "diff clipped" notice — not file content.
        case truncation
    }

    let id: Int
    let kind: Kind
    let text: String

    /// The leading glyph. A real minus sign (U+2212) rather than a hyphen so it
    /// optically matches `+` at the same monospaced width.
    var gutter: String {
        switch kind {
        case .removed: "\u{2212}"
        case .added: "+"
        case .truncation: ""
        }
    }
}

/// Pure, testable projection of an `EntityDiff` into rows.
struct DiffModel {
    /// Mirrors `git_service._DIFF_TRUNCATION_MARKER`. Keep the two in lockstep:
    /// the backend appends this line to a clipped side, and we promote it out of
    /// the content stream into its own `.truncation` row.
    static let truncationMarker = "... [diff truncated]"

    let lines: [DiffLine]
    let truncated: Bool

    var isEmpty: Bool { lines.isEmpty }

    init(_ diff: EntityDiff) {
        var out: [DiffLine] = []
        var next = 0

        func append(_ block: String, as kind: DiffLine.Kind) {
            guard !block.isEmpty else { return }
            // `separator:omittingEmptySubsequences: false` keeps blank lines that
            // are real file content; the trailing-newline artifact is dropped.
            var raw = block.components(separatedBy: "\n")
            if raw.last == "" { raw.removeLast() }
            for text in raw {
                let isMarker = text == Self.truncationMarker
                out.append(DiffLine(id: next, kind: isMarker ? .truncation : kind, text: text))
                next += 1
            }
        }

        append(diff.removed, as: .removed)
        append(diff.added, as: .added)

        self.lines = out
        self.truncated = diff.truncated
    }
}

/// GitHub-style inline diff: monospaced, `+`/`−` gutters, green/red text on a
/// tinted row background.
struct DiffView: View {
    let model: DiffModel

    init(diff: EntityDiff) {
        self.model = DiffModel(diff)
    }

    private static let addedColor = Color(hex: 0x22C55E)
    private static let removedColor = Color(hex: 0xEF4444)

    var body: some View {
        if model.isEmpty {
            Self.empty
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(model.lines) { line in
                    row(line)
                }
                if model.truncated {
                    Text("Diff clipped — this commit changed more than we show here.")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .padding(.horizontal, CicadaTheme.spacingSM)
                        .padding(.vertical, CicadaTheme.spacingXS)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(CicadaTheme.surfaceHover.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
    }

    @ViewBuilder
    private func row(_ line: DiffLine) -> some View {
        switch line.kind {
        case .truncation:
            Text(line.text)
                .font(CicadaTheme.monoFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.vertical, 1)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .added, .removed:
            let color = line.kind == .added ? Self.addedColor : Self.removedColor
            HStack(alignment: .top, spacing: CicadaTheme.spacingXS) {
                Text(line.gutter)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(color.opacity(0.8))
                    .frame(width: 10, alignment: .leading)
                Text(line.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(color)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 1)
            .background(color.opacity(0.10))
        }
    }

    /// Shown while a per-commit diff is in flight.
    static var loading: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            ProgressView().controlSize(.small)
            Text("Loading diff…")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingSM)
    }

    /// Shown when the commit did not change this file (or the fetch failed).
    static var empty: some View {
        Text("No line changes for this entity in this commit.")
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
