import Foundation

enum GatewayNames {
  static let maxLength = 60

  static func valid(_ raw: String?) -> String? {
    guard let name = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty, name.count <= maxLength else { return nil }
    guard !name.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { return nil }
    return name
  }

  static func same(_ a: String, _ b: String) -> Bool {
    a.caseInsensitiveCompare(b) == .orderedSame
  }
}
