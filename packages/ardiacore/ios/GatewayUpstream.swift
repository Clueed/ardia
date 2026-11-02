import Foundation

final class GatewayUpstream: NSObject, URLSessionWebSocketDelegate {
  private var session: URLSession!
  private var task: URLSessionWebSocketTask!
  private var closed = false
  private var opened = false
  private var waiting: [String] = []
  var onOpen: (() -> Void)?
  var onText: ((String) -> Void)?
  var onClose: (() -> Void)?

  init(url: URL, queue: DispatchQueue) {
    super.init()
    let operations = OperationQueue()
    operations.underlyingQueue = queue
    operations.maxConcurrentOperationCount = 1
    session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: operations)
    task = session.webSocketTask(with: url)
    task.maximumMessageSize = GatewaySocket.maxMessage
  }

  func start() {
    task.resume()
    receive()
  }

  func send(_ text: String) {
    guard !closed else { return }
    guard opened else { return waiting.append(text) }
    task.send(.string(text)) { [weak self] error in
      if error != nil { self?.finish() }
    }
  }

  func close() {
    guard !closed else { return }
    task.cancel(with: .normalClosure, reason: nil)
    finish()
  }

  private func receive() {
    task.receive { [weak self] result in
      guard let self, !self.closed else { return }
      switch result {
      case .success(.string(let text)):
        self.onText?(text)
        self.receive()
      case .success(.data(let data)):
        self.onText?(String(decoding: data, as: UTF8.self))
        self.receive()
      case .success:
        self.receive()
      case .failure:
        self.finish()
      }
    }
  }

  func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
    opened = true
    let queued = waiting
    waiting = []
    for text in queued { send(text) }
    onOpen?()
  }

  func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
    finish()
  }

  func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
    finish()
  }

  private func finish() {
    guard !closed else { return }
    closed = true
    session.invalidateAndCancel()
    let done = onClose
    onClose = nil
    onText = nil
    onOpen = nil
    done?()
  }
}
