import AppKit

/// Rasterizes a 16x16 `#`-grid (plus optional overlays) into a template
/// `NSImage` for the menu bar. Template mode means the menu bar tints the lit
/// pixels for dark + light appearance — the fill color here is irrelevant.
enum BookwormRenderer {
    /// Authored grid dimension (cells per side).
    static let gridSize = 16

    /// Render one frame into a template `NSImage` of `pointSize` x `pointSize`.
    /// `overlays` (badge digits, stage dots, zZz) are OR-ed onto the base grid
    /// before rasterizing.
    static func image(
        grid: [String],
        overlays: [[String]] = [],
        pointSize: CGFloat = 16
    ) -> NSImage {
        // Merge overlays onto a mutable copy of the base grid.
        var rows: [[Character]] = grid.map { line in
            var chars = Array(line)
            // Pad/truncate every row to exactly gridSize so ragged authoring
            // (trailing spaces stripped by an editor) never crashes indexing.
            if chars.count < gridSize {
                chars.append(contentsOf: Array(repeating: " ", count: gridSize - chars.count))
            } else if chars.count > gridSize {
                chars = Array(chars.prefix(gridSize))
            }
            return chars
        }
        // Guard the row count too.
        if rows.count < gridSize {
            rows.append(contentsOf: Array(
                repeating: Array(repeating: Character(" "), count: gridSize),
                count: gridSize - rows.count
            ))
        } else if rows.count > gridSize {
            rows = Array(rows.prefix(gridSize))
        }

        for overlay in overlays {
            for (r, line) in overlay.enumerated() where r < gridSize {
                for (c, cell) in line.enumerated() where c < gridSize {
                    if cell == "#" { rows[r][c] = "#" }
                }
            }
        }

        let size = NSSize(width: pointSize, height: pointSize)
        let cell = pointSize / CGFloat(gridSize)

        let image = NSImage(size: size, flipped: false) { _ in
            NSColor.black.setFill()
            // Grid row 0 is the top; AppKit's origin is bottom-left, so flip the
            // row index when computing y.
            for (r, line) in rows.enumerated() {
                for (c, ch) in line.enumerated() where ch == "#" {
                    let x = CGFloat(c) * cell
                    let y = CGFloat(gridSize - 1 - r) * cell
                    NSBezierPath(rect: NSRect(x: x, y: y, width: cell, height: cell)).fill()
                }
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}
