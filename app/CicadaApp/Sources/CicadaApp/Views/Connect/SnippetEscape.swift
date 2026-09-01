import Foundation

/// Per-format escaping for the filesystem paths `AgentSetupCatalog` bakes
/// into its copy-paste snippets (Devin PR #28 round 2). A home like
/// `/Users/Jane Doe` — spaces are common on macOS — or one carrying a quote
/// or a backslash used to paste as a broken or silently altered
/// command/config. Every helper is the identity for a path with nothing to
/// escape, so the common case stays byte-identical to what the page has
/// always shown.
enum SnippetEscape {
    /// A bare shell word. Anything a POSIX shell would interpret makes the
    /// whole word single-quoted, with an embedded `'` spelled `'\''`
    /// (close, escaped quote, reopen) — the one idiom that needs no other
    /// escaping, since nothing else is special inside single quotes.
    static func shell(_ path: String) -> String {
        if path.allSatisfy(isShellSafe) { return path }
        return "'" + path.replacingOccurrences(of: "'", with: #"'\''"#) + "'"
    }

    /// The body of a word the snippet already wraps in `"…"` (the openclaw,
    /// codex and gemini commands, kept in the double-quoted form verified
    /// against their docs). Only what double quotes still interpret is
    /// escaped: `\`, `"`, `$` and the backtick.
    static func shellDoubleQuoted(_ path: String) -> String {
        var out = ""
        for c in path {
            if c == "\\" || c == "\"" || c == "$" || c == "`" { out.append("\\") }
            out.append(c)
        }
        return out
    }

    /// The body of a JSON string: `\`, `"` and control characters.
    static func json(_ path: String) -> String { quotedBody(path) }

    /// The body of a TOML basic string — the same escape set as JSON
    /// (`\b \t \n \f \r \" \\ \uXXXX`), plus DEL, which TOML also forbids raw.
    static func toml(_ path: String) -> String { quotedBody(path) }

    /// The body of a YAML double-quoted scalar; YAML accepts every escape
    /// JSON does, so the two coincide.
    static func yaml(_ path: String) -> String { quotedBody(path) }

    /// Letters, digits and the punctuation a path plausibly carries that no
    /// POSIX shell reads specially (`~` stays bare so a leading tilde still
    /// expands exactly as it did). Non-ASCII is never special to the shell.
    private static func isShellSafe(_ c: Character) -> Bool {
        guard c.isASCII else { return true }
        return c.isLetter || c.isNumber || "/._-~+@%:,=".contains(c)
    }

    /// Escapes `\`, `"`, the named C0 controls, and every other control
    /// character (plus DEL) as `\uXXXX` — a form JSON, TOML basic strings
    /// and YAML double-quoted scalars all read identically.
    private static func quotedBody(_ s: String) -> String {
        var out = ""
        for scalar in s.unicodeScalars {
            switch scalar {
            case "\\": out += "\\\\"
            case "\"": out += "\\\""
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if scalar.value < 0x20 || scalar.value == 0x7F {
                    out += String(format: "\\u%04X", scalar.value)
                } else {
                    out.unicodeScalars.append(scalar)
                }
            }
        }
        return out
    }
}
