import SwiftUI

// G67/G69 — the shared commit-diff renderer.
//
// One component, two call sites: the entity detail card's History tab (a tapped
// commit row expands into it) and the Contributors drill-down (a tapped entity
// chip on a commit). The parsing/ordering/gutter decisions live in `DiffModel`
// so they are testable without a view hierarchy; `DiffView` only paints.
//
// G69: the backend now sends `lines` — a REAL unified diff (`git show -U4`),
// ordered, with the unchanged context around each change and git's own old/new
// line numbers on every row. We render it GitHub-style: two slim number
// gutters, a +/−/space marker, then the text. The pre-G69 shape (two
// newline-joined `added`/`removed` blocks, interleaving already lost) is still
// handled: when `lines` is absent — an older backend, or a payload cached
// before the upgrade — we fall back to rendering removals then additions as
// blocks, exactly as before, with no line numbers.

/// Identifies one (entity, commit) pair's diff-fetch state. The same commit
/// hash routinely appears in more than one entity's history — one Sleep-cycle
/// commit commonly touches several entity files — so a commit hash alone is
/// never a safe cache key: keying by hash alone let one entity's cached diff
/// leak into another entity's row for a shared commit (G67 fix round 1).
/// Shared by both call sites (`EntityDetailCard`'s History tab,
/// `ContributorsSection`'s commit drill-down) so the composition rule lives in
/// one place and is unit-testable without a view hierarchy.
struct DiffCacheKey: Hashable {
    let entityId: String
    let commitHash: String
}

/// One rendered diff row.
struct DiffLine: Identifiable, Equatable {
    enum Kind: Equatable {
        case context
        case removed
        case added
        /// A `@@ -a,b +c,d @@` hunk header — a jump in the file, not content.
        case hunk
        /// The backend's "diff clipped" notice — not file content.
        case truncation
    }

    let id: Int
    let kind: Kind
    let text: String
    /// Line number in the file BEFORE the commit. Present on context and
    /// removal rows; nil on additions, hunk headers, and in the legacy
    /// two-block fallback (which has no line information at all).
    let oldLine: Int?
    /// Line number in the file AFTER the commit. Present on context and
    /// addition rows; nil otherwise (see `oldLine`).
    let newLine: Int?

    init(id: Int, kind: Kind, text: String, oldLine: Int? = nil, newLine: Int? = nil) {
        self.id = id
        self.kind = kind
        self.text = text
        self.oldLine = oldLine
        self.newLine = newLine
    }

    /// The leading glyph. A real minus sign (U+2212) rather than a hyphen so it
    /// optically matches `+` at the same monospaced width. Context rows get a
    /// space so their text stays column-aligned with the changed lines.
    var gutter: String {
        switch kind {
        case .removed: "\u{2212}"
        case .added: "+"
        case .context: " "
        case .hunk, .truncation: ""
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
    /// True when this model came from the backend's ordered `lines` — i.e. it
    /// has real context rows and line numbers, so the view draws the number
    /// gutters. False for the legacy two-block fallback, which has neither.
    let hasLineNumbers: Bool

    var isEmpty: Bool { lines.isEmpty }

    /// Widest line number the gutters must fit, as a digit count (minimum 2 so
    /// a one-line file doesn't produce a hairline-thin column).
    var lineNumberDigits: Int {
        guard hasLineNumbers else { return 0 }
        let widest = lines.reduce(0) { max($0, max($1.oldLine ?? 0, $1.newLine ?? 0)) }
        return max(2, String(widest).count)
    }

    init(_ diff: EntityDiff) {
        self.truncated = diff.truncated

        if !diff.lines.isEmpty {
            self.hasLineNumbers = true
            self.lines = diff.lines.enumerated().map { index, wire in
                DiffLine(
                    id: index,
                    kind: Self.kind(for: wire.kind),
                    text: wire.text,
                    oldLine: wire.oldLine,
                    newLine: wire.newLine
                )
            }
            return
        }

        // --- legacy fallback: two newline-joined blocks, no ordering, no numbers
        self.hasLineNumbers = false
        var out: [DiffLine] = []
        var next = 0

        func append(_ block: String, as kind: DiffLine.Kind) {
            guard !block.isEmpty else { return }
            // `components(separatedBy:)` keeps blank lines that are real file
            // content; the trailing-newline artifact is dropped.
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
    }

    /// Wire `kind` → row kind. An unrecognised value renders as plain context
    /// rather than dropping the row or failing the payload.
    private static func kind(for wire: String) -> DiffLine.Kind {
        switch wire {
        case "add": .added
        case "remove": .removed
        case "hunk": .hunk
        default: .context
        }
    }
}

/// Width of the diff container, measured so every row can be at least that wide
/// — otherwise a row inside the horizontal `ScrollView` shrinks to its own text
/// and the tinted add/remove background stops short of the right edge.
private struct DiffContainerWidthKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

/// GitHub-style unified diff: monospaced, old/new line-number gutters, a
/// `+`/`−`/space marker, and full-row tinting on changed lines. Long lines
/// scroll horizontally INSIDE the container — never the page.
struct DiffView: View {
    let model: DiffModel

    @State private var containerWidth: CGFloat = 0

    init(diff: EntityDiff) {
        self.model = DiffModel(diff)
    }

    // Routed through CicadaTheme (not raw hex literals) so light mode gets its
    // own deepened-for-contrast variant instead of the dark-tuned value
    // rendering unchanged in both themes (G67 fix round 1).
    private static var addedColor: Color { CicadaTheme.diffAdded }
    private static var removedColor: Color { CicadaTheme.diffRemoved }

    /// Monospaced digits are ~0.6em wide; 12pt mono ⇒ ~7.2pt per digit, plus
    /// padding either side of the column.
    private var numberColumnWidth: CGFloat {
        model.hasLineNumbers ? CGFloat(model.lineNumberDigits) * 7.5 + 10 : 0
    }

    var body: some View {
        if model.isEmpty {
            Self.empty
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ScrollView(.horizontal, showsIndicators: true) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(model.lines) { line in
                            row(line)
                        }
                    }
                }
                .background(
                    GeometryReader { proxy in
                        Color.clear.preference(
                            key: DiffContainerWidthKey.self, value: proxy.size.width
                        )
                    }
                )
                .onPreferenceChange(DiffContainerWidthKey.self) { containerWidth = $0 }

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

    // MARK: - Rows

    @ViewBuilder
    private func row(_ line: DiffLine) -> some View {
        switch line.kind {
        case .truncation:
            Text(line.text)
                .font(CicadaTheme.monoFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .fixedSize(horizontal: true, vertical: false)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.vertical, 1)
                .frame(minWidth: containerWidth, alignment: .leading)
        case .hunk:
            // A jump in the file — the "⋯" says "lines skipped here".
            HStack(spacing: CicadaTheme.spacingXS) {
                Text("\u{22EF}")
                Text(line.text)
            }
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .fixedSize(horizontal: true, vertical: false)
            .padding(.horizontal, CicadaTheme.spacingSM)
            .padding(.vertical, 2)
            .frame(minWidth: containerWidth, alignment: .leading)
            .background(CicadaTheme.surfaceElevated.opacity(0.6))
        case .context, .added, .removed:
            contentRow(line)
        }
    }

    private func contentRow(_ line: DiffLine) -> some View {
        let tint: Color? = switch line.kind {
        case .added: Self.addedColor
        case .removed: Self.removedColor
        default: nil
        }

        // The vertical padding lives on the CELLS, not on the row: the gutter
        // cells paint their own (slightly stronger) tint, and if the row owned
        // the padding their background would fall 2pt short of the row's,
        // leaving a sliver of mismatched color above and below every number.
        return HStack(spacing: 0) {
            if model.hasLineNumbers {
                number(line.oldLine, tint: tint)
                number(line.newLine, tint: tint)
            }
            HStack(spacing: 0) {
                Text(line.gutter)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle((tint ?? CicadaTheme.textTertiary).opacity(0.8))
                    .frame(width: 12, alignment: .leading)
                    .padding(.leading, CicadaTheme.spacingSM)
                Text(line.text)
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(tint ?? CicadaTheme.textSecondary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: true, vertical: false)
                    .padding(.trailing, CicadaTheme.spacingSM)
            }
            .padding(.vertical, 1)
        }
        .frame(minWidth: containerWidth, alignment: .leading)
        .background(tint?.opacity(0.10) ?? Color.clear)
    }

    /// One line-number cell. Muted, right-aligned, and never selected by a
    /// drag over the diff — a copied selection should be the file's text, not
    /// its numbering.
    private func number(_ value: Int?, tint: Color?) -> some View {
        Text(value.map(String.init) ?? "")
            .font(CicadaTheme.monoFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .frame(width: numberColumnWidth, alignment: .trailing)
            .padding(.trailing, 4)
            .padding(.vertical, 1)
            .background((tint ?? CicadaTheme.textTertiary).opacity(tint == nil ? 0.04 : 0.10))
    }

    // MARK: - States

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

    /// Shown when the commit did not change this file for real — no fetch
    /// error, the diff genuinely came back empty.
    static var empty: some View {
        Text("No line changes for this entity in this commit.")
            .font(CicadaTheme.captionFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Shown when the fetch itself failed (G67 fix round 1) — distinct from
    /// `empty` so a network hiccup doesn't read as "this commit changed
    /// nothing here". Tapping retries via the caller-supplied closure.
    static func error(onRetry: @escaping () -> Void) -> some View {
        Button(action: onRetry) {
            HStack(spacing: CicadaTheme.spacingXS) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(CicadaTheme.diffRemoved)
                Text("Couldn't load this diff — tap to retry")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(CicadaTheme.spacingSM)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
