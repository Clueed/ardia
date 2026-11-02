import Foundation
import Security

enum GatewayTokens {
  static func random(bytes count: Int = 32) -> String {
    var bytes = [UInt8](repeating: 0, count: count)
    if SecRandomCopyBytes(kSecRandomDefault, count, &bytes) != errSecSuccess {
      for i in bytes.indices { bytes[i] = UInt8.random(in: 0...255) }
    }
    return Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
  }

  static func equal(_ given: String, _ expected: String) -> Bool {
    let a = Array(given.utf8)
    let b = Array(expected.utf8)
    guard !b.isEmpty, a.count == b.count else { return false }
    var difference: UInt8 = 0
    for i in a.indices { difference |= a[i] ^ b[i] }
    return difference == 0
  }
}
