import SwiftUI

// MARK: - TranscludingMarkdownView
//
// Inline transclusion (§1 of d2-companion-showcase.md). Replaces the flat
// `Text(renderedMarkdownAttributed(...))` inside EntityDetailCard. It tokenizes
// the body into `.text(AttributedString)` / `.embed(ref:)` segments (one regex
// pass for `!\[\[(.+?)\]\]`, the residual text rendered with the existing
// wikilink machinery), then renders a VStack where each embed is an inline,
// collapsible, depth-guarded TransclusionCard. Tapping an embed's title calls
// the existing `graphVM.selectEntity(id:)` hook.

enum MarkdownSegment {
    // Raw markdown text (headings, lists, code fences, prose, `[[wikilinks]]`,
    // real links — everything BUT `![[embed]]` / `![alt](url)` tokens, which
    // are split out into their own segments below). Rendered via
    // `MarkdownBody`, a real block-level markdown renderer — see that file.
    case text(String)
    case embed(ref: String)
    // G11: an inline markdown image `![alt](url)`. Rendered as an
    // `ImageThumbnail` (tap → lightbox), reusing the media preview machinery.
    case image(url: String, alt: String)
}

struct TranscludingMarkdownView: View {
    let body0: String
    var depth: Int = 0
    var visited: Set<String> = []
    @Environment(GraphViewModel.self) private var graphVM

    init(body: String, depth: Int = 0, visited: Set<String> = []) {
        self.body0 = body
        self.depth = depth
        self.visited = visited
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, seg in
                switch seg {
                case .text(let raw):
                    if !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        MarkdownBody(text: raw)
                    }
                case .embed(let ref):
                    if depth >= 2 || visited.contains(ref) {
                        cyclicStub(ref)
                    } else {
                        TransclusionCard(ref: ref, depth: depth + 1, visited: visited.union([ref]))
                    }
                case .image(let url, let alt):
                    if let u = URL(string: url) {
                        VStack(alignment: .leading, spacing: 4) {
                            ImageThumbnail(url: u, width: 320, height: 180)
                            if !alt.isEmpty {
                                Text(alt)
                                    .font(CicadaTheme.captionFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                        }
                    } else {
                        Text(alt.isEmpty ? url : alt)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                }
            }
        }
        // Wikilinks are rewritten (by `MarkdownBody`) into ordinary markdown
        // links pointed at a synthetic `cicada://entity/<id>` URL. Intercept
        // that scheme here and route it to the graph's entity navigation;
        // everything else (http/https) falls through to the system handler
        // (opens in the default browser). `selectEntity` already no-ops
        // gracefully (logs + leaves selection untouched) if `<id>` doesn't
        // resolve to a real entity, so a stale/typo'd wikilink can't crash.
        .environment(\.openURL, OpenURLAction { url in
            guard url.scheme == "cicada" else { return .systemAction }
            let id = url.lastPathComponent
            if !id.isEmpty {
                graphVM.selectEntity(id: id)
            }
            return .handled
        })
    }

    /// Tokenize `body0` into text/embed/image segments. A single regex pass
    /// matches BOTH `![[ref]]` wikilink embeds AND `![alt](url)` markdown images
    /// (alternation; whichever group matched decides the segment kind — the
    /// embed alternative is tried first so `![[x]]` never mis-parses as an
    /// image). Residual text is passed through RAW (no wikilink processing
    /// here) — `MarkdownBody` owns full block + inline markdown rendering,
    /// including `[[wikilinks]]`, for each `.text` segment.
    private var segments: [MarkdownSegment] {
        // Group 1: embed ref (`![[ref]]`). Groups 2/3: image alt + url (`![alt](url)`).
        let pattern = "!\\[\\[(.+?)\\]\\]|!\\[([^\\]]*)\\]\\(([^)]+)\\)"
        guard let regex = try? NSRegularExpression(pattern: pattern) else {
            return [.text(body0)]
        }
        let nsText = body0 as NSString
        var out: [MarkdownSegment] = []
        var lastEnd = 0
        let matches = regex.matches(in: body0, range: NSRange(location: 0, length: nsText.length))
        for match in matches {
            let beforeRange = NSRange(location: lastEnd, length: match.range.location - lastEnd)
            if beforeRange.length > 0 {
                out.append(.text(nsText.substring(with: beforeRange)))
            }
            if match.range(at: 1).location != NSNotFound {
                // `![[ref]]` embed.
                out.append(.embed(ref: nsText.substring(with: match.range(at: 1))))
            } else if match.range(at: 3).location != NSNotFound {
                // `![alt](url)` markdown image.
                let alt = match.range(at: 2).location != NSNotFound
                    ? nsText.substring(with: match.range(at: 2)) : ""
                let url = nsText.substring(with: match.range(at: 3))
                out.append(.image(url: url, alt: alt))
            }
            lastEnd = match.range.location + match.range.length
        }
        if lastEnd < nsText.length {
            out.append(.text(nsText.substring(from: lastEnd)))
        }
        if out.isEmpty { out.append(.text(body0)) }
        return out
    }

    /// Depth-cap / cycle stub — `A ![[B]]` / `B ![[A]]` degrade here.
    private func cyclicStub(_ ref: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 10))
            Text("cyclic embed · \(ref)")
                .font(CicadaTheme.captionFont)
        }
        .foregroundStyle(CicadaTheme.textTertiary)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .padding(.vertical, CicadaTheme.spacingXS)
        .background(CicadaTheme.surfaceHover.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

// MARK: - TransclusionCard
//
// Resolves one `![[…]]` ref via `GET /transclude` and renders the result as a
// nested, collapsible, accent-barred card. For a `claim:` ref it shows the
// ClaimChip (§5); for an `entity#facet` ref it renders that facet's valid
// claims; for a bare entity it shows the generated one-liner. Tapping the title
// click-throughs to that entity in the graph detail card.

struct TransclusionCard: View {
    let ref: String
    var depth: Int
    var visited: Set<String>
    @Environment(GraphViewModel.self) private var graphVM

    @State private var payload: TransclusionPayload?
    @State private var isLoading = true
    @State private var collapsed = false

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            // Thin left accent bar — "this is embedded from elsewhere".
            Rectangle()
                .fill(CicadaTheme.accent.opacity(0.7))
                .frame(width: 3)

            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                header
                if !collapsed { content }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(CicadaTheme.surface.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(CicadaTheme.border, lineWidth: 1)
        )
        .task { await load() }
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button { collapsed.toggle() } label: {
                Image(systemName: collapsed ? "chevron.right" : "chevron.down")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .buttonStyle(.plain)

            Image(systemName: "rectangle.on.rectangle.angled")
                .font(.system(size: 10))
                .foregroundStyle(CicadaTheme.accent)

            // Tap the title → click-through to the embedded entity.
            Button {
                graphVM.selectEntity(id: targetEntityID)
            } label: {
                Text(payload?.title ?? ref)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.accent)
                    .lineLimit(1)
            }
            .buttonStyle(.plain)
            .help("Open \(targetEntityID)")

            Spacer()

            Text("transcluded")
                .font(.system(size: 9, weight: .regular, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            ProgressView().controlSize(.small)
        } else if let p = payload {
            if !p.resolved {
                missingStub
            } else if let media = p.mediaURL, let u = URL(string: media),
                      MediaURLHelpers.isImageURL(media) {
                // G11: a media entity that surfaced an image url → render the
                // image inline (tap → lightbox) instead of a text summary.
                // Degrades to the summary branches below when no image url is
                // present (the common case until the backend emits it).
                VStack(alignment: .leading, spacing: 4) {
                    ImageThumbnail(url: u, width: 300, height: 170)
                    if !p.summary.isEmpty {
                        Text(p.summary)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                    }
                }
            } else if p.kind == "claim" || p.kind == "facet" {
                if p.claims.isEmpty {
                    Text(p.summary.isEmpty ? "No current claims." : p.summary)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                } else {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                        ForEach(p.claims) { claim in
                            ClaimChip(claim: claim)
                        }
                    }
                }
            } else {
                // Bare entity: generated one-liner summary.
                Text(p.summary.isEmpty ? "No summary." : p.summary)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            missingStub
        }
    }

    private var missingStub: some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 10))
            Text("![[\(ref)]] not found")
                .font(CicadaTheme.captionFont)
        }
        .foregroundStyle(CicadaTheme.textTertiary)
    }

    /// Strip the `claim:` prefix / `#facet` / `?context=` selectors down to the
    /// bare subject id for the graph click-through.
    private var targetEntityID: String {
        var id = ref
        if id.hasPrefix("claim:") {
            // A claim ref has no entity id to navigate to; fall back to the
            // resolved subject of the first claim if available.
            if let subj = payload?.claims.first?.subject, !subj.isEmpty { return subj }
            return id
        }
        if let hash = id.firstIndex(of: "#") { id = String(id[..<hash]) }
        if let q = id.firstIndex(of: "?") { id = String(id[..<q]) }
        return id
    }

    private func load() async {
        isLoading = true
        payload = try? await APIClient.shared.resolveTransclusion(ref)
        isLoading = false
    }
}
