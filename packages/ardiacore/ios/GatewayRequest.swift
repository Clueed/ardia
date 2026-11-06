import Foundation

struct GatewayRequest {
  let method: String
  let path: String
  let query: [String: String]
  let headers: [String: String]
  let leftover: [UInt8]

  var wantsSocket: Bool { headers["upgrade"]?.lowercased() == "websocket" }
}
