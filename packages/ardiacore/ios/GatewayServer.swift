import CryptoKit
import Foundation
import Network

final class GatewayServer {
  private static let headLimit = 16 << 10
  private static let headDeadline: TimeInterval = 10
  private static let maxHeads = 32
  private static let maxConnections = 256
  private static let socketGuid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

  private let queue: DispatchQueue
  private var listener: NWListener?
  private(set) var port: UInt16 = 0
  private var heads = 0
  private var live = 0
  var onRequest: ((GatewayRequest, NWConnection) -> Void)?

  init(queue: DispatchQueue) {
    self.queue = queue
  }

  func start(ready: @escaping (UInt16?) -> Void) {
    stop()
    let parameters = NWParameters.tcp
    parameters.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: .any)
    parameters.acceptLocalOnly = true
    guard let listener = try? NWListener(using: parameters) else { return ready(nil) }
    self.listener = listener
    var reported = false
    listener.stateUpdateHandler = { [weak self, weak listener] state in
      guard let self, !reported else { return }
      switch state {
      case .ready where listener != nil && listener === self.listener:
        reported = true
        self.port = listener?.port?.rawValue ?? 0
        ready(self.port)
      case .ready, .failed, .cancelled:
        reported = true
        listener?.cancel()
        ready(nil)
      default:
        break
      }
    }
    listener.newConnectionHandler = { [weak self] connection in self?.accept(connection) }
    listener.start(queue: queue)
  }

  func stop() {
    listener?.cancel()
    listener = nil
    port = 0
  }

  private func accept(_ connection: NWConnection) {
    guard heads < Self.maxHeads, live < Self.maxConnections else { return connection.cancel() }
    heads += 1
    live += 1
    var counted = true
    connection.stateUpdateHandler = { [weak self] state in
      switch state {
      case .cancelled, .failed:
        guard counted else { return }
        counted = false
        self?.live -= 1
      default:
        break
      }
    }
    connection.start(queue: queue)
    var head: [UInt8] = []
    var finished = false
    var done: Bool {
      get { finished }
      set {
        if newValue && !finished { self.heads -= 1 }
        finished = newValue
      }
    }
    queue.asyncAfter(deadline: .now() + Self.headDeadline) {
      if !done {
        done = true
        connection.cancel()
      }
    }
    func read() {
      connection.receive(minimumIncompleteLength: 1, maximumLength: Self.headLimit) { [weak self] data, _, complete, error in
        guard let self, !done else { return }
        if let data { head.append(contentsOf: data) }
        if let end = Self.headEnd(head) {
          done = true
          guard let request = Self.parse(Array(head[..<end]), leftover: Array(head[(end + 4)...])) else {
            return Self.respond(connection, status: 400, json: ["error": "bad-request"])
          }
          return self.onRequest?(request, connection) ?? connection.cancel()
        }
        if head.count > Self.headLimit || complete || error != nil {
          done = true
          return connection.cancel()
        }
        read()
      }
    }
    read()
  }

  private static func headEnd(_ bytes: [UInt8]) -> Int? {
    guard bytes.count >= 4 else { return nil }
    for i in 0...(bytes.count - 4) where bytes[i] == 13 && bytes[i + 1] == 10 && bytes[i + 2] == 13 && bytes[i + 3] == 10 { return i }
    return nil
  }

  private static func parse(_ head: [UInt8], leftover: [UInt8]) -> GatewayRequest? {
    let lines = String(decoding: head, as: UTF8.self).components(separatedBy: "\r\n")
    let start = lines.first?.split(separator: " ", omittingEmptySubsequences: true) ?? []
    guard start.count == 3, start[2].hasPrefix("HTTP/1.") else { return nil }
    var headers: [String: String] = [:]
    for line in lines.dropFirst() where !line.isEmpty {
      guard let colon = line.firstIndex(of: ":") else { return nil }
      let name = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
      headers[name] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
    }
    guard let components = URLComponents(string: "http://gateway" + start[1]) else { return nil }
    var query: [String: String] = [:]
    for item in components.queryItems ?? [] { query[item.name] = item.value ?? "" }
    return GatewayRequest(method: String(start[0]), path: components.path, query: query, headers: headers, leftover: leftover)
  }

  static func respond(_ connection: NWConnection, status: Int, json: Any) {
    let body = (try? JSONSerialization.data(withJSONObject: json, options: [.fragmentsAllowed])) ?? Data("{}".utf8)
    let head = "HTTP/1.1 \(status) \(reason(status))\r\nContent-Type: application/json\r\nContent-Length: \(body.count)\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
    connection.send(content: Data(head.utf8) + body, isComplete: true, completion: .contentProcessed { _ in connection.cancel() })
  }

  static func upgrade(_ connection: NWConnection, _ request: GatewayRequest) -> Bool {
    guard request.headers["sec-websocket-version"] == "13", let key = request.headers["sec-websocket-key"], !key.isEmpty else { return false }
    let accept = Data(Insecure.SHA1.hash(data: Data((key + socketGuid).utf8))).base64EncodedString()
    let head = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: \(accept)\r\n\r\n"
    connection.send(content: Data(head.utf8), completion: .contentProcessed { _ in })
    return true
  }

  private static func reason(_ status: Int) -> String {
    switch status {
    case 200: "OK"
    case 400: "Bad Request"
    case 403: "Forbidden"
    case 404: "Not Found"
    case 405: "Method Not Allowed"
    case 409: "Conflict"
    case 429: "Too Many Requests"
    case 502: "Bad Gateway"
    case 504: "Gateway Timeout"
    default: "Error"
    }
  }
}
