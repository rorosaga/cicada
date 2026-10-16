import Compression
import Foundation

/// What the LinkedIn tile posts for Connections (2026-10-16): only `Connections.csv`'s bytes. LinkedIn's data export
/// `.zip` also carries the person's messages, invitations and more, and is often past the backend's 32 MB cap — so the
/// app opens the archive itself, reads its central directory and that ONE member, and never reads any other member's
/// bytes into memory or onto the wire. A lone `Connections.csv` is posted as it is.
struct LinkedInConnectionsPayload: Equatable {
    let data: Data
    /// The day the export's facts are true as of: a lone CSV's modification day, or the archive member's own date.
    let exportedOn: String?
    let filename = "Connections.csv"
}

enum LinkedInConnectionsFileError: Error, Equatable, LocalizedError {
    case noConnections
    case tooLarge
    case unreadable

    var errorDescription: String? {
        switch self {
        case .noConnections:
            return "That archive has no Connections.csv. Request LinkedIn's data export with Connections ticked, then drop the new .zip."
        case .tooLarge:
            return "Connections.csv is too large to be LinkedIn's connections export."
        case .unreadable:
            return "That archive could not be read. Unzip it and choose the Connections.csv inside."
        }
    }
}

enum LinkedInConnectionsFile {
    /// The backend's own cap on what it reads (`linkedin_people.MAX_BYTES`).
    static let maxBytes = 32 * 1024 * 1024
    /// A central directory past this is no LinkedIn export (thousands of members would fit in far less).
    static let maxDirectoryBytes = 16 * 1024 * 1024

    static func payload(for url: URL, modified: Date? = nil) throws -> LinkedInConnectionsPayload {
        if url.pathExtension.lowercased() == "zip" {
            let found = try connectionsFromZip(url)
            return LinkedInConnectionsPayload(data: found.data, exportedOn: found.day)
        }
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0
        guard size <= maxBytes else { throw LinkedInConnectionsFileError.tooLarge }
        guard let data = try? Data(contentsOf: url) else { throw LinkedInConnectionsFileError.unreadable }
        return LinkedInConnectionsPayload(data: data,
                                          exportedOn: LinkedInConnectionsWords.exportedOn(fileURL: url, modified: modified))
    }

    /// The archive's shallowest `Connections.csv` and its member date, read through the central directory: only the
    /// archive's tail, the directory and that one member's bytes are read.
    static func connectionsFromZip(_ url: URL) throws -> (data: Data, day: String?) {
        guard let handle = try? FileHandle(forReadingFrom: url) else { throw LinkedInConnectionsFileError.unreadable }
        defer { try? handle.close() }
        func read(_ offset: UInt64, _ count: Int) throws -> Data {
            do {
                try handle.seek(toOffset: offset)
                guard let data = try handle.read(upToCount: count), data.count == count else {
                    throw LinkedInConnectionsFileError.unreadable
                }
                return data
            } catch let error as LinkedInConnectionsFileError {
                throw error
            } catch {
                throw LinkedInConnectionsFileError.unreadable
            }
        }
        guard let end = try? handle.seekToEnd(), end >= 22 else { throw LinkedInConnectionsFileError.unreadable }

        // End of central directory: the last 22 bytes plus up to a 64 KB comment.
        let tailCount = Int(min(end, 22 + 65_535))
        let tail = try read(end - UInt64(tailCount), tailCount)
        guard let eocd = stride(from: tail.count - 22, through: 0, by: -1).first(where: { tail.u32($0) == 0x0605_4b50 })
        else { throw LinkedInConnectionsFileError.unreadable }
        let directorySize = tail.u32(eocd + 12)
        let directoryOffset = tail.u32(eocd + 16)
        // ZIP64 (an archive past 4 GB) is no connections export.
        guard directorySize != 0xFFFF_FFFF, directoryOffset != 0xFFFF_FFFF, Int(directorySize) <= maxDirectoryBytes,
              UInt64(directoryOffset) + UInt64(directorySize) <= end
        else { throw LinkedInConnectionsFileError.unreadable }
        let directory = try read(UInt64(directoryOffset), Int(directorySize))

        struct Member { let name: String; let flags: UInt16; let method: UInt16; let date: UInt16
                        let compressed: UInt32; let size: UInt32; let offset: UInt32 }
        var members: [Member] = []
        var at = 0
        while at + 46 <= directory.count, directory.u32(at) == 0x0201_4b50 {
            let nameCount = Int(directory.u16(at + 28))
            let extraCount = Int(directory.u16(at + 30))
            let commentCount = Int(directory.u16(at + 32))
            guard at + 46 + nameCount <= directory.count else { break }
            let nameBytes = directory.subdata(in: (directory.startIndex + at + 46)..<(directory.startIndex + at + 46 + nameCount))
            let name = String(decoding: nameBytes, as: UTF8.self)
            if !name.hasSuffix("/"), (name as NSString).lastPathComponent.lowercased() == "connections.csv" {
                members.append(Member(name: name, flags: directory.u16(at + 8), method: directory.u16(at + 10),
                                      date: directory.u16(at + 14), compressed: directory.u32(at + 20),
                                      size: directory.u32(at + 24), offset: directory.u32(at + 42)))
            }
            at += 46 + nameCount + extraCount + commentCount
        }
        guard let member = members.min(by: { $0.name.split(separator: "/").count < $1.name.split(separator: "/").count })
        else { throw LinkedInConnectionsFileError.noConnections }
        guard Int(member.size) <= maxBytes, Int(member.compressed) <= maxBytes else {
            throw LinkedInConnectionsFileError.tooLarge
        }
        // Encrypted (bit 0) or a method other than stored / deflate: not LinkedIn's archive.
        guard member.flags & 0x1 == 0, member.method == 0 || member.method == 8 else {
            throw LinkedInConnectionsFileError.unreadable
        }

        let local = try read(UInt64(member.offset), 30)
        guard local.u32(0) == 0x0403_4b50 else { throw LinkedInConnectionsFileError.unreadable }
        let start = UInt64(member.offset) + 30 + UInt64(local.u16(26)) + UInt64(local.u16(28))
        guard start + UInt64(member.compressed) <= end else { throw LinkedInConnectionsFileError.unreadable }
        let packed = member.compressed == 0 ? Data() : try read(start, Int(member.compressed))
        let data = member.method == 0 ? packed : try inflate(packed, size: Int(member.size))
        guard data.count == Int(member.size) else { throw LinkedInConnectionsFileError.unreadable }
        return (data, dosDay(member.date))
    }

    /// Raw DEFLATE (a zip member's method 8) into exactly `size` bytes.
    static func inflate(_ packed: Data, size: Int) throws -> Data {
        guard size > 0 else { return Data() }
        var out = Data(count: size)
        let written = out.withUnsafeMutableBytes { dst -> Int in
            packed.withUnsafeBytes { src -> Int in
                guard let d = dst.bindMemory(to: UInt8.self).baseAddress,
                      let s = src.bindMemory(to: UInt8.self).baseAddress else { return 0 }
                return compression_decode_buffer(d, size, s, packed.count, nil, COMPRESSION_ZLIB)
            }
        }
        guard written == size else { throw LinkedInConnectionsFileError.unreadable }
        return out
    }

    /// An MS-DOS date (a zip member's) as `yyyy-MM-dd`, or nil when it is not a day.
    static func dosDay(_ value: UInt16) -> String? {
        let day = Int(value & 0x1f), month = Int((value >> 5) & 0xf), year = Int(value >> 9) + 1980
        guard (1...31).contains(day), (1...12).contains(month) else { return nil }
        return String(format: "%04d-%02d-%02d", year, month, day)
    }
}

private extension Data {
    func u16(_ at: Int) -> UInt16 {
        UInt16(self[startIndex + at]) | UInt16(self[startIndex + at + 1]) << 8
    }

    func u32(_ at: Int) -> UInt32 {
        UInt32(u16(at)) | UInt32(u16(at + 2)) << 16
    }
}
