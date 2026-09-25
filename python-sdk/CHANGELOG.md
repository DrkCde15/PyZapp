# Changelog

All notable changes to `pyzapp-sdk` follow [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-09-25

### Changed
- PyPI page rewrite (quickstart-first README), runnable `examples/`,
  SDK test matrix (Python 3.10–3.14) in CI

## [0.2.0] - 2026-09-25

### Added
- AI auto-reply: `set_ai`, `get_ai`, `disable_ai` (OpenAI, Groq, OpenRouter,
  Ollama, Gemini, Anthropic)
- `print_qr`: fetch the QR and print it as ASCII in the terminal
- `request_pairing_code`: link via 8-digit code instead of QR scan

## [0.1.0] - 2026-09-25

### Added
- Initial release: instances, QR/status, text messages, webhooks
- Typed models (pydantic) and mapped errors with stable codes
